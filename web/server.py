"""
Web UI sederhana untuk giveaway_grok.

Jalankan di Termux / komputer manapun:

    python web/server.py

lalu buka di browser HP yang sama:

    http://127.0.0.1:8000

Server ini:
- Tidak memerlukan dependency eksternal (cukup stdlib Python).
- Tidak menyimpan log permanen.
- Tidak menerima API key dari browser; key dibaca dari env XAI_API_KEY
  di komputer/HP yang menjalankan server ini.
- Hanya bind ke 127.0.0.1 secara default agar tidak bisa diakses dari
  jaringan luar. Lihat --host kalau memang ingin LAN-share.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Pastikan kita bisa import giveaway_grok.py yang ada di parent folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from giveaway_grok import (  # noqa: E402
    call_grok,
    offline_generate,
    parse_grok_output,
)

INDEX_HTML_PATH = Path(__file__).with_name("index.html")


class Handler(BaseHTTPRequestHandler):
    server_version = "GiveawayGrok/1.0"

    # --- helpers ---------------------------------------------------------
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path, content_type: str) -> None:
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # --- routes ----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_file(INDEX_HTML_PATH, "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self._send_json(
                200,
                {
                    "online": bool(os.environ.get("XAI_API_KEY", "").strip()),
                    "model": os.environ.get("XAI_MODEL", "grok-4-latest"),
                },
            )
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/generate":
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 32_000:  # batasi 32 KB
            self._send_json(400, {"error": "Body kosong atau terlalu besar."})
            return

        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Body bukan JSON valid."})
            return

        post = (body.get("post") or "").strip()
        n = int(body.get("n") or 3)
        force_offline = bool(body.get("offline"))

        if not post:
            self._send_json(400, {"error": "Field 'post' kosong."})
            return
        if n < 1 or n > 10:
            self._send_json(400, {"error": "n harus 1..10"})
            return

        api_key = os.environ.get("XAI_API_KEY", "").strip()
        used_mode = "offline"
        try:
            if force_offline or not api_key:
                raw = offline_generate(post, n)
                used_mode = "offline"
            else:
                raw = call_grok(
                    post,
                    n,
                    os.environ.get("XAI_MODEL", "grok-4-latest"),
                    api_key,
                )
                used_mode = "online"
        except Exception as e:  # noqa: BLE001
            self._send_json(502, {"error": f"Gagal memanggil Grok: {e}"})
            return

        try:
            result = parse_grok_output(raw, n)
        except (ValueError, json.JSONDecodeError) as e:
            self._send_json(
                502,
                {"error": f"Gagal parse output: {e}", "raw": raw},
            )
            return

        self._send_json(
            200,
            {
                "mode": used_mode,
                "language": result.language,
                "prize": result.prize,
                "host": result.host,
                "reasoning": result.reasoning,
                "comments": result.comments,
            },
        )

    # diam-diam: matikan log baris by baris bawaan, ganti yang ringkas
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        sys.stderr.write(f"[web] {self.address_string()} {format % args}\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Giveaway Grok web UI")
    p.add_argument("--host", default="127.0.0.1",
                   help="Alamat bind. Default 127.0.0.1 (lokal saja).")
    p.add_argument("--port", type=int, default=8000, help="Port (default 8000).")
    args = p.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    has_key = bool(os.environ.get("XAI_API_KEY", "").strip())
    print(f"Giveaway Grok web UI", file=sys.stderr)
    print(f"  - listen     : http://{args.host}:{args.port}", file=sys.stderr)
    print(f"  - mode       : {'ONLINE (Grok API)' if has_key else 'OFFLINE (template)'}",
          file=sys.stderr)
    if not has_key:
        print("  - tip        : set XAI_API_KEY untuk pakai Grok asli",
              file=sys.stderr)
    print("  - tekan Ctrl+C untuk berhenti", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye.", file=sys.stderr)


if __name__ == "__main__":
    main()
