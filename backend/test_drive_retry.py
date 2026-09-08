# -*- coding: utf-8 -*-
"""A dropped socket is not a missing folder.

Every write on the Drive client already retries with a fresh API client, because a broken SSL
session lives inside the cached per-thread one. Listing did not, and listing is the most-called
path there is — list_folders and list_images both come through it. A run that holds a connection
open for an hour outlives it: run #129 died in the pool step, and the wrong-wheel apply died on
its very last read, after every file had already been moved and every customer picture rebuilt.
"""
import os
import ssl
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
os.environ["PHOTO_OCR_DATA"] = tempfile.mkdtemp(prefix="pocr-drive-")
sys.path.insert(0, "backend")

import drive_client                                             # noqa: E402

ok = True


def check(name, cond):
    global ok
    print(("✅" if cond else "✗"), name)
    ok = ok and cond


class FakeFiles:
    def __init__(self, outcomes):
        self.outcomes, self.calls = outcomes, 0

    def list(self, **kw):
        self.kw = kw
        return self

    def execute(self):
        out = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(out, Exception):
            raise out
        return out


class FakeSvc:
    def __init__(self, outcomes):
        self._f = FakeFiles(outcomes)

    def files(self):
        return self._f


def client(outcomes):
    """A DriveClient without its constructor — no credentials, no network, just the paging."""
    c = object.__new__(drive_client.DriveClient)
    svc = FakeSvc(outcomes)
    c._local = type("L", (), {})()
    c._local.svc = svc
    c._build = lambda *a, **k: svc          # a rebuilt client is the same fake
    c._creds = None
    type(c)._sleep_for_test = None
    return c, svc


import time                                                     # noqa: E402
_real_sleep = time.sleep
time.sleep = lambda *_a: None                                    # the backoff, without the wait

EOF_ERR = ssl.SSLEOFError("EOF occurred in violation of protocol (_ssl.c:2427)")

c, svc = client([EOF_ERR, {"files": [{"id": "a", "name": "x.jpg"}]}])
got = c._list("q", "id, name")
check("ต่อหลุดครั้งแรก แล้วลองใหม่ได้ผล", [r["id"] for r in got] == ["a"])
check("ลองจริง 2 ครั้ง", svc._f.calls == 2)

c2, svc2 = client([EOF_ERR, EOF_ERR, EOF_ERR, EOF_ERR])
try:
    c2._list("q", "id, name")
    check("ถ้าหลุดทุกครั้ง ต้องโยน error ไม่ใช่ตอบว่าว่าง", False)
except ssl.SSLEOFError:
    check("ถ้าหลุดทุกครั้ง ต้องโยน error ไม่ใช่ตอบว่าว่าง", True)
check("ไม่ลองไม่จบไม่สิ้น หยุดที่ 3 ครั้ง", svc2._f.calls == 3)

# paging must survive a drop in the middle without losing or repeating a page
c3, svc3 = client([
    {"files": [{"id": "p1"}], "nextPageToken": "t1"},
    EOF_ERR,
    {"files": [{"id": "p2"}]},
])
got3 = [r["id"] for r in c3._list("q", "id")]
check("หน้าที่สองหลุด แล้วต่อได้ ไม่ข้ามไม่ซ้ำ", got3 == ["p1", "p2"])
check("ขอหน้าถัดไปด้วย token เดิม", svc3._f.kw.get("pageToken") == "t1")

# a folder that really is empty still answers empty
c4, _ = client([{"files": []}])
check("โฟลเดอร์ที่ว่างจริง ยังตอบว่าว่างตามปกติ", c4._list("q", "id") == [])

# list_images and list_folders both go through it
c5, svc5 = client([EOF_ERR, {"files": [{"id": "i", "name": "a.jpg",
                                        "mimeType": "image/jpeg", "webViewLink": "u"}]}])
check("list_images ได้รับการป้องกันด้วย", [i["id"] for i in c5.list_images("f")] == ["i"])
c6, _ = client([EOF_ERR, {"files": [{"id": "d", "name": "ก"}]}])
check("list_folders ได้รับการป้องกันด้วย", [f["id"] for f in c6.list_folders("f")] == ["d"])

time.sleep = _real_sleep
print("\nสรุป:", "ผ่านทั้งหมด ✅" if ok else "มีข้อที่ไม่ผ่าน ✗")
sys.exit(0 if ok else 1)
