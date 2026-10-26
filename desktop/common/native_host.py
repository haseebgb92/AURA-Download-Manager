"""AURA authorized native-messaging bridge; no secret ever goes to an extension.

Browser-enforced host manifests allow only the installed AURA extension.
This one-shot process forwards a bounded request to the authenticated local
desktop service and writes only native-messaging frames to stdout.
"""
from __future__ import annotations

import json
import os
import pathlib
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request

HOST_NAME = "com.advertpreneur.aura"
API = "http://127.0.0.1:18763"
MAX_MESSAGE = 64 * 1024
MAX_REPLY = 1024 * 1024
SUPPORTED = {
    "status": ("GET", "/status"),
    "add": ("POST", "/add"),
    "stream": ("POST", "/stream"),
    "formats": ("POST", "/yt/formats"),
    "yt_add": ("POST", "/yt/add"),
}
APP_DIR = ((pathlib.Path(os.environ["LOCALAPPDATA"]) / "AURA-Download-Manager")
           if os.name == "nt" and os.getenv("LOCALAPPDATA")
           else pathlib.Path.home() / ".local/share/aura-download-manager")
TOKEN_PATH = APP_DIR / "bridge.token"


def valid_url(url: object) -> bool:
    if not isinstance(url, str) or len(url) > 4096:
        return False
    try:
        parts = urllib.parse.urlsplit(url)
        return (
            parts.scheme in ("http", "https") and bool(parts.hostname)
            and not parts.username and not parts.password
        )
    except ValueError:
        return False


def process_message(message: object) -> dict:
    if not isinstance(message, dict):
        return {"ok": False, "error": "Invalid request."}
    command = message.get("command")
    if command not in SUPPORTED:
        return {"ok": False, "error": "Unsupported AURA command."}
    method, path = SUPPORTED[command]
    payload = None
    if method == "POST":
        url = message.get("url")
        if not valid_url(url):
            return {"ok": False, "error": "A valid HTTP or HTTPS URL is required."}
        if command == "stream" and message.get("kind") not in ("hls", "dash"):
            return {"ok": False, "error": "Invalid stream type."}
        if command == "yt_add" and not isinstance(message.get("quality"), str):
            return {"ok": False, "error": "Missing quality."}
        payload = {"url": url, "intent": "user"}
        if command == "stream":
            payload["kind"] = message["kind"]
        if command == "yt_add":
            payload["quality"] = message["quality"]
    try:
        # AURA's private token remains on the device, never returned to Chrome/Firefox.
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(token) < 24:
            raise ValueError("Invalid local credential")
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            API + path,
            data=body,
            headers={"X-Aura-Token": token, **({"Content-Type": "application/json"} if body else {})},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=6) as reply:
            data = reply.read(MAX_REPLY + 1)
            if len(data) > MAX_REPLY:
                return {"ok": False, "error": "AURA response exceeded allowed size."}
            result = json.loads(data)
            return result if isinstance(result, dict) else {"ok": False, "error": "Invalid desktop response."}
    except FileNotFoundError:
        return {"ok": False, "error": "Start AURA Download Manager to connect automatically."}
    except urllib.error.HTTPError as exc:
        try:
            problem = json.loads(exc.read(2048))
            return {"ok": False, "error": str(problem.get("error") or f"AURA error {exc.code}")[:320]}
        except (ValueError, TypeError):
            return {"ok": False, "error": f"AURA returned error {exc.code}."}
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return {"ok": False, "error": "AURA is offline. Open the desktop app and retry."}
    except (OSError, ValueError):
        return {"ok": False, "error": "Cannot access AURA's local connection."}


def read_frame(stream) -> object:
    header = stream.read(4)
    if len(header) != 4:
        raise EOFError("Missing native message length.")
    length = struct.unpack("=I", header)[0]
    if length < 2 or length > MAX_MESSAGE:
        raise ValueError("Native request exceeds AURA limit.")
    data = stream.read(length)
    if len(data) != length:
        raise EOFError("Truncated native request.")
    return json.loads(data.decode("utf-8"))


def write_frame(stream, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_REPLY:
        data = b'{"ok":false,"error":"AURA response is too large."}'
    stream.write(struct.pack("=I", len(data)))
    stream.write(data)
    stream.flush()


def main() -> int:
    if os.name == "nt":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    try:
        request = read_frame(sys.stdin.buffer)
        response = process_message(request)
    except (ValueError, EOFError, UnicodeError, json.JSONDecodeError):
        response = {"ok": False, "error": "Invalid browser message."}
    write_frame(sys.stdout.buffer, response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
