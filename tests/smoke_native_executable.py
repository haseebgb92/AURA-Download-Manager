"""Smoke-test a packaged Windows native host executable without a browser."""
import json
import pathlib
import struct
import subprocess
import sys

exe = pathlib.Path(sys.argv[1]).resolve()
assert exe.is_file(), f"Missing native host: {exe}"
message = json.dumps({"command": "status"}).encode("utf-8")
packet = struct.pack("=I", len(message)) + message
run = subprocess.run([str(exe)], input=packet, capture_output=True, timeout=25)
assert run.returncode == 0, f"Native host exit {run.returncode}"
assert len(run.stdout) >= 6, f"No framed reply: {len(run.stdout)} bytes"
length = struct.unpack("=I", run.stdout[:4])[0]
assert length == len(run.stdout) - 4, "Corrupt native message frame"
answer = json.loads(run.stdout[4:].decode("utf-8"))
assert isinstance(answer, dict) and isinstance(answer.get("ok"), bool), answer
assert "token" not in json.dumps(answer).lower(), "Browser must never receive a desktop token"
print(f"Packaged native host protocol OK (desktop connected={answer['ok']})")
