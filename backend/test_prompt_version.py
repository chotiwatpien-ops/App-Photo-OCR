# -*- coding: utf-8 -*-
"""ทุกแถวบอกได้ว่า prompt รุ่นไหนอ่าน (Fiat 2026-11-25). Almost every row is approved with nobody
looking, and a row only stored its model, so a new prompt could not be compared with the old one.
Each read now carries a version made from the prompt and the settings sent with it.

The request is built in one place for both read paths. That must not alter what is sent, so the
first half of this file compares what reaches Gemini with the request put together by hand from
the same building blocks, the way the code did before."""
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-version-")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, "backend")

from google.genai import types                                  # noqa: E402

import batch_client                                             # noqa: E402
import config                                                   # noqa: E402
import db                                                       # noqa: E402
import extractor                                                # noqa: E402
import pipeline                                                 # noqa: E402

db.init_db()
ok = True


def check(name, cond, got=None):
    global ok
    print(("✅" if cond else "✗"), name, "" if cond or got is None else f"→ {got}")
    ok = ok and bool(cond)


@contextmanager
def changed(obj, name, value):
    before = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, before)


MODEL = "gemini-3.7-flash"
config.GEMINI_MODEL = extractor.GEMINI_MODEL = MODEL
config.PASSENGER_LINES, config.EXTRACT_DROP_FIELDS = False, ()
extractor.GEMINI_THINKING_LEVEL, extractor.GEMINI_THINKING_BUDGET = "low", 0
PIC, MIME = b"a slip picture", "image/jpeg"
DROP = ("pickup_text", "dropoff_text")


def answer(n):
    return json.dumps({"kind": "full", "net_earnings": 80.0, "base_fare": 80.0, "distance_km": 3.2,
                       "booking_code": f"A-TESTKEY{n:04d}AV"})


class FakeGemini:
    """Stands where genai.Client does. It keeps every request it is handed. A batch is answered
    at once and each answer carries its request's metadata back, as the real queue does."""

    def __init__(self):
        self.live, self.jobs = [], {}
        self.models = SimpleNamespace(generate_content=self._read)
        self.batches = SimpleNamespace(create=self._create, get=lambda name: self.jobs[name])
        self.files = SimpleNamespace(download=lambda file: self.jobs[file])

    def _read(self, **request):
        self.live.append(request)
        usage = SimpleNamespace(prompt_token_count=900, candidates_token_count=120,
                                thoughts_token_count=0)
        return SimpleNamespace(text=answer(len(self.live)), usage_metadata=usage)

    def _create(self, model, src, config):
        name = f"batches/fake{len(self.jobs) + 1}"
        self.finished(name, model, [(dict(r.metadata), answer(100 + int(r.metadata["trip_id"])))
                                    for r in src])
        self.jobs[name].requests = src
        return SimpleNamespace(name=name)

    def finished(self, name, model, answers):
        usage = SimpleNamespace(prompt_token_count=900, candidates_token_count=120,
                                thoughts_token_count=0)
        responses = [SimpleNamespace(metadata=meta, error=None,
                                     response=SimpleNamespace(text=text, usage_metadata=usage))
                     for meta, text in answers]
        self.jobs[name] = SimpleNamespace(state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
                                          model=f"models/{model}",
                                          dest=SimpleNamespace(inlined_responses=responses))


gemini = FakeGemini()
extractor._client = gemini


def by_hand(drop=(), lines=False):
    """The prompt and the config as extractor.prompt() and _gen_config() were combined at each
    call site before read_request existed."""
    props = dict(extractor.SCHEMA.properties)
    if lines:
        props.update(extractor.PASSENGER_LINE_PROPS)
    schema = extractor.SCHEMA if not (drop or lines) else types.Schema(
        type=types.Type.OBJECT, properties={k: v for k, v in props.items() if k not in drop},
        required=extractor.SCHEMA.required)
    return (extractor.PROMPT + (extractor.PASSENGER_LINE_RULES if lines else ""),
            types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema,
                                        temperature=0,
                                        thinking_config=types.ThinkingConfig(thinking_level="low")))


picture = types.Part.from_bytes(data=PIC, mime_type=MIME)
for label, drop, lines in (("ค่าตั้งต้น", (), False), ("ตัดช่องออก", DROP, False),
                           ("เปิดบรรทัดผู้โดยสาร", (), True)):
    text, cfg = by_hand(drop, lines)
    with changed(config, "EXTRACT_DROP_FIELDS", drop), changed(config, "PASSENGER_LINES", lines):
        req = extractor.read_request(MODEL, drop)
        check(f"{label}: read_request ให้ prompt และ config เท่าของเดิม",
              req.prompt == text and req.config == cfg and req.model == MODEL)

        gemini.live.clear()
        extractor.extract_image(PIC, MIME, drop=config.EXTRACT_DROP_FIELDS)
        check(f"{label}: อ่านสดส่งคำขอเดิม",
              gemini.live == [{"model": MODEL, "contents": [text, picture], "config": cfg}])

        job = batch_client.submit([(7, PIC, MIME)])[0]
        sent = gemini.jobs[job["name"]].requests
        check(f"{label}: batch ส่งคำขอเดิม",
              len(sent) == 1 and sent[0].model == MODEL and sent[0].contents == [text, picture]
              and sent[0].config == cfg and sent[0].metadata["trip_id"] == "7" and job["model"] == MODEL)
        check(f"{label}: batch ติดรุ่นเดียวกับที่อ่านสดรายงาน",
              sent[0].metadata.get("prompt_version") == req.version, sent[0].metadata)

text, cfg = by_hand(lines=True)
gemini.live.clear()
extractor.extract_image(PIC, MIME, lines=True)
check("สั่ง lines=True ตรง ๆ ขณะสวิตช์ปิด (ทางที่ reread_passenger ใช้): ส่งคำขอเดิม",
      gemini.live == [{"model": MODEL, "contents": [text, picture], "config": cfg}])

base = extractor.read_request(MODEL).version
check("รุ่นเป็นเลขฐานสิบหก 10 ตัว", re.fullmatch(r"[0-9a-f]{10}", base), base)
check("เรียกซ้ำได้รุ่นเดิม", extractor.read_request(MODEL).version == base)
check("ชื่อโมเดลอย่างเดียวไม่ขยับรุ่น (แถวเก็บ model ไว้อีกช่องแล้ว)",
      extractor.read_request("gemini-3.5-flash-lite").version == base)

moved = {"ตัดช่องออก": extractor.read_request(MODEL, DROP).version,
         "เปิดบรรทัดผู้โดยสาร": extractor.read_request(MODEL, lines=True).version}
with changed(extractor, "GEMINI_THINKING_LEVEL", "high"):
    moved["ระดับการคิด"] = extractor.read_request(MODEL).version
with changed(extractor, "PROMPT", extractor.PROMPT + "- A new rule.\n"):
    moved["ข้อความ prompt"] = extractor.read_request(MODEL).version
reworded = extractor.SCHEMA.model_copy(deep=True)
reworded.properties["turbo"].description += " Not the event fee."
with changed(extractor, "SCHEMA", reworded):
    moved["คำอธิบายช่องใน schema"] = extractor.read_request(MODEL).version
reordered = extractor.SCHEMA.model_copy(deep=True)
reordered.properties = dict(reversed(list(reordered.properties.items())))
with changed(extractor, "SCHEMA", reordered):
    moved["ลำดับช่องใน schema"] = extractor.read_request(MODEL).version
for what, version in moved.items():
    check(f"เปลี่ยน{what}: รุ่นขยับ", version != base, version)
check("แต่ละการเปลี่ยนได้รุ่นของตัวเอง", len(set(moved.values())) == len(moved), moved)
check("เลิกเปลี่ยนแล้วกลับเป็นรุ่นเดิม", extractor.read_request(MODEL).version == base)

job_id = db.create_job("ก Home", "Trips", "2026-11-23", "2026-11-29", category="2 W Saver")


def slip(name):
    return db.create_trip(job_id, name, PIC, MIME)


live_row = slip("1.jpg")
check("อ่านสด: สำเร็จ", pipeline.process_trip(live_row, job_id) == "done", db.get_trip(live_row))
row = db.get_trip(live_row)
check("อ่านสด: แถวเก็บรุ่นและโมเดล", (row["prompt_version"], row["model"]) == (base, MODEL),
      (row["prompt_version"], row["model"]))

batch_row = slip("2.jpg")
sent_job = batch_client.submit([(batch_row, PIC, MIME)])[0]
with changed(extractor, "PROMPT", extractor.PROMPT + "- A rule added after the batch went out.\n"):
    now = extractor.read_request(MODEL).version
    state, data, errors = batch_client.collect(sent_job["name"])
    check("batch: เก็บผลได้", state.endswith("SUCCEEDED") and batch_row in data and not errors,
          (state, errors))
    pipeline.apply_extraction(batch_row, job_id, data[batch_row])
row = db.get_trip(batch_row)
check("batch: prompt เปลี่ยนระหว่างรอผล แถวยังเก็บรุ่นตอนส่ง",
      row["status"] == "done" and row["prompt_version"] == base and now != base
      and row["model"] == MODEL, (row["status"], row["prompt_version"], now, row["model"]))

old_row = slip("3.jpg")
gemini.finished("batches/old", MODEL, [({"trip_id": str(old_row)}, answer(3))])
state, data, errors = batch_client.collect("batches/old")
pipeline.apply_extraction(old_row, job_id, data[old_row])
row = db.get_trip(old_row)
check("batch เก่าไม่มีรุ่นติดมา: แถวเป็น NULL ไม่ใช่รุ่นปัจจุบัน",
      row["status"] == "done" and row["prompt_version"] is None and row["model"] == MODEL,
      (row["status"], row["prompt_version"], row["model"]))

stamped, bare = slip("4.jpg"), slip("5.jpg")


def line(trip_id, n, **meta):
    return json.dumps({"metadata": {"trip_id": str(trip_id), **meta},
                       "response": {"candidates": [{"content": {"parts": [{"text": answer(n)}]}}],
                                    "usageMetadata": {"promptTokenCount": 900}}})


gemini.jobs["batches/file"] = SimpleNamespace(state=SimpleNamespace(name="JOB_STATE_SUCCEEDED"),
                                              model=f"models/{MODEL}",
                                              dest=SimpleNamespace(file_name="files/answers"))
gemini.jobs["files/answers"] = "\n".join([line(stamped, 4, prompt_version="0123456789"),
                                          line(bare, 5)]).encode("utf-8")
state, data, errors = batch_client.collect("batches/file")
for trip_id in (stamped, bare):
    pipeline.apply_extraction(trip_id, job_id, data[trip_id])
check("ผล batch ที่มาเป็นไฟล์: ได้รุ่นตอนส่ง และ NULL เมื่อไม่มี",
      (db.get_trip(stamped)["prompt_version"], db.get_trip(bare)["prompt_version"])
      == ("0123456789", None),
      (db.get_trip(stamped)["prompt_version"], db.get_trip(bare)["prompt_version"]))

db.update_trip(bare, {"prompt_version": "abcdef0123"})
check("update_trip เขียน prompt_version ได้", db.get_trip(bare)["prompt_version"] == "abcdef0123")

elsewhere = [p.name for p in sorted(Path(__file__).parent.glob("*.py"))
             if p.name != "extractor.py" and not p.name.startswith("test_")
             and re.search(r"_gen_config\(|extractor\.prompt\(", p.read_text(encoding="utf-8"))]
check("ไม่มีไฟล์อื่นประกอบคำขออ่านเอง (ต้องผ่าน extractor.read_request)", not elsewhere, elsewhere)

print("\nผ่านทั้งหมด" if ok else "\nมีข้อที่ไม่ผ่าน")
sys.exit(0 if ok else 1)
