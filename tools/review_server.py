"""Local review page: listen to each clip and fix the Lingala / French text.

Usage: python tools/review_server.py   then open http://localhost:8765

Saves straight into dataset/clips/<id>/metadata.jsonl (fields lingala, francais,
lang, needs_review). Only listens on localhost.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset"
CLIPS = DATASET / "clips"
PAGE = Path(__file__).with_name("review.html")
LOCK = threading.Lock()
EDITABLE = {"lingala", "francais", "lang", "needs_review"}


def meta_path(vid):
    p = (CLIPS / vid / "metadata.jsonl").resolve()
    if CLIPS.resolve() not in p.parents:
        raise ValueError("bad id")
    return p


def read_rows(vid):
    return [json.loads(l) for l in meta_path(vid).read_text(encoding="utf-8").splitlines() if l.strip()]


def titles():
    out = []
    for d in sorted(p for p in CLIPS.iterdir() if p.is_dir()):
        t = DATASET / "raw" / d.name / "title.txt"
        out.append({"id": d.name, "title": t.read_text(encoding="utf-8").strip() if t.exists() else d.name})
    return out


class H(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/":
                return self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/videos":
                return self.send(200, titles())
            if u.path == "/api/clips":
                return self.send(200, read_rows(q["id"][0]))
            if u.path.startswith("/clips/") and u.path.endswith(".wav"):
                p = (DATASET / unquote(u.path.lstrip("/"))).resolve()
                if CLIPS.resolve() in p.parents and p.exists():
                    return self.send(200, p.read_bytes(), "audio/wav")
            self.send(404, {"error": "not found"})
        except (KeyError, ValueError, FileNotFoundError) as e:
            self.send(400, {"error": str(e)})

    def do_POST(self):
        if self.path != "/api/save":
            return self.send(404, {"error": "not found"})
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        vid, audio = body["video_id"], body["audio"]
        with LOCK:
            rows = read_rows(vid)
            for r in rows:
                if r["audio"] == audio:
                    r.update({k: v for k, v in body.items() if k in EDITABLE})
                    break
            else:
                return self.send(404, {"error": "clip not found"})
            meta_path(vid).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        self.send(200, {"ok": True})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print("Revision: http://localhost:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), H).serve_forever()
