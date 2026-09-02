# -*- coding: utf-8 -*-
"""Gemini Batch API: half the token price, and a round that submits instead of waiting.

A live round holds a GitHub runner open while Gemini answers one image at a time — 30 minutes
for 300 images, and the free 2,000 Actions minutes a month go in about a week. A batch round
hands the whole pile over and leaves; the next round picks the answers up. Same model, same
prompt, same schema — Google simply charges half for work it may take its time over.

Submitted images stay `pending` with their blob, so nothing is lost if a batch fails: the
trips are still there to read the ordinary way.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import config
import extractor

# One create call carries the images inline. The request body has a hard ceiling, so the pile
# is cut into chunks well under it — a slip is ~140 KB, and base64 inflates it by a third.
MAX_CHUNK_BYTES = 12 * 1024 * 1024
MAX_CHUNK_ITEMS = 60


def _client():
    return extractor.client()


def _chunks(items):
    chunk, size = [], 0
    for trip_id, image, mime in items:
        grew = size + int(len(image) * 1.34)
        if chunk and (grew > MAX_CHUNK_BYTES or len(chunk) >= MAX_CHUNK_ITEMS):
            yield chunk
            chunk, size = [], 0
            grew = int(len(image) * 1.34)
        chunk.append((trip_id, image, mime))
        size = grew
    if chunk:
        yield chunk


def submit(items, model=None, display_name="ingest", workers=4) -> list:
    """Hand images to the batch queue. items = [(trip_id, image_bytes, mime)].

    Returns [{"name": job name, "trips": [trip_id, ...]}] — one entry per chunk. The trip id
    rides along as request metadata, so results identify themselves on the way back."""
    from google.genai import types
    model = model or config.GEMINI_MODEL
    cl = _client()
    cfg = extractor._gen_config(model, config.EXTRACT_DROP_FIELDS)   # same schema as a live read

    def one(numbered):
        i, chunk = numbered
        requests = [
            types.InlinedRequest(
                model=model,
                contents=[extractor.PROMPT,
                          types.Part.from_bytes(data=img, mime_type=mime)],
                config=cfg,
                metadata={"trip_id": str(trip_id)},
            )
            for trip_id, img, mime in chunk
        ]
        job = cl.batches.create(model=model, src=requests,
                                config={"display_name": f"{display_name}-{i + 1}"})
        return {"name": job.name, "trips": [t for t, _, _ in chunk], "model": model}

    chunks = list(enumerate(_chunks(items)))
    if len(chunks) <= 1:
        return [one(c) for c in chunks]
    # each create uploads its images, so a big round is worth sending in parallel
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(chunks)))) as ex:
        return list(ex.map(one, chunks))


def state(name) -> str:
    """One of JOB_STATE_PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED / EXPIRED."""
    job = _client().batches.get(name=name)
    return str(getattr(job.state, "name", job.state) or "")


def collect(name):
    """Results for a finished batch: (state, {trip_id: data}, {trip_id: error message}).

    While the job is still queued or running both dicts come back empty — the caller simply
    tries again next round. A single request that failed inside a successful batch is reported
    per trip, not as a whole-batch failure."""
    cl = _client()
    job = cl.batches.get(name=name)
    st = str(getattr(job.state, "name", job.state) or "")
    if not st.endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")):
        return st, {}, {}
    data, errors = {}, {}
    dest = job.dest
    responses = list(getattr(dest, "inlined_responses", None) or []) if dest else []
    for r in responses:
        tid = int((r.metadata or {}).get("trip_id", 0) or 0)
        if not tid:
            continue
        if r.error:
            errors[tid] = str(getattr(r.error, "message", r.error))[:300]
            continue
        try:
            data[tid] = _parse(r.response, job.model or config.GEMINI_MODEL)
        except Exception as e:  # noqa: BLE001
            errors[tid] = f"อ่านผลจาก batch ไม่ได้: {str(e)[:200]}"
    if st.endswith("SUCCEEDED") and not responses:
        # a succeeded job with a file destination instead of inline responses
        fname = getattr(dest, "file_name", None) if dest else None
        if fname:
            for line in cl.files.download(file=fname).decode("utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                tid = int((row.get("metadata") or {}).get("trip_id", 0) or 0)
                if not tid:
                    continue
                if row.get("error"):
                    errors[tid] = str(row["error"])[:300]
                else:
                    try:
                        data[tid] = _parse_dict(row.get("response") or {},
                                                job.model or config.GEMINI_MODEL)
                    except Exception as e:  # noqa: BLE001
                        errors[tid] = f"อ่านผลจาก batch ไม่ได้: {str(e)[:200]}"
    return st, data, errors


def _parse(response, model):
    text = response.text
    if not text:
        raise RuntimeError("คำตอบว่าง")
    out = json.loads(text)
    u = response.usage_metadata
    out["_usage"] = {"model": (model or "").split("/")[-1],
                     "tok_in": getattr(u, "prompt_token_count", 0) or 0,
                     "tok_out": getattr(u, "candidates_token_count", 0) or 0,
                     "tok_think": getattr(u, "thoughts_token_count", 0) or 0}
    return out


def _parse_dict(response: dict, model: str):
    parts = (response.get("candidates") or [{}])[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise RuntimeError("คำตอบว่าง")
    out = json.loads(text)
    u = response.get("usageMetadata") or {}
    out["_usage"] = {"model": (model or "").split("/")[-1],
                     "tok_in": u.get("promptTokenCount", 0) or 0,
                     "tok_out": u.get("candidatesTokenCount", 0) or 0,
                     "tok_think": u.get("thoughtsTokenCount", 0) or 0}
    return out


def wait(name, timeout=600, every=15):
    """Block until a batch finishes — for testing from a terminal, never inside a round."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = state(name)
        if st.endswith(("SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED")):
            return st
        time.sleep(every)
    return state(name)
