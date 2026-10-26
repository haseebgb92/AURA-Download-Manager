"""Install least-privileged AURA Chrome and Firefox native host manifests."""
from __future__ import annotations
import argparse
import json
import os
import pathlib
import re

NAME = "com.advertpreneur.aura"
ID_PATTERN = re.compile(r"^[a-p]{32}$")
FIREFOX_ID = "aura-download-manager@local"


def chrome_ids(extension_root: pathlib.Path, chrome_root: pathlib.Path) -> set[str]:
    trusted = extension_root.resolve()
    found: set[str] = set()
    if not chrome_root.exists():
        return found
    for prefs in chrome_root.glob("*/Preferences"):
        try:
            profile = json.loads(prefs.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for ident, entry in profile.get("extensions", {}).get("settings", {}).items():
            if not ID_PATTERN.fullmatch(ident):
                continue
            path = entry.get("path")
            if not path:
                continue
            try:
                if pathlib.Path(path).expanduser().resolve() == trusted:
                    found.add(ident)
            except (OSError, RuntimeError):
                continue
    return found


def write_manifest(path: pathlib.Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)


def register_linux(host_path: pathlib.Path, chrome_ext: pathlib.Path,
                   home: pathlib.Path, chrome_root: pathlib.Path) -> dict:
    ids = chrome_ids(chrome_ext, chrome_root)
    base = {
        "name": NAME, "description": "AURA Download Manager by Advertpreneur",
        "path": str(host_path.resolve()), "type": "stdio",
    }
    # Chrome requires an exact allowlist. Never use a wildcard or authorize every extension.
    google = home / ".config/google-chrome/NativeMessagingHosts" / f"{NAME}.json"
    chromium = home / ".config/chromium/NativeMessagingHosts" / f"{NAME}.json"
    firefox = home / ".mozilla/native-messaging-hosts" / f"{NAME}.json"
    write_manifest(firefox, {**base, "allowed_extensions": [FIREFOX_ID]})
    if ids:
        origins = [f"chrome-extension://{ident}/" for ident in sorted(ids)]
        for path in (google, chromium):
            write_manifest(path, {**base, "allowed_origins": origins})
    return {"chrome_ids": sorted(ids), "firefox": str(firefox), "chrome_ready": bool(ids)}


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--host", type=pathlib.Path, required=True)
    cli.add_argument("--chrome-extension", type=pathlib.Path, required=True)
    cli.add_argument("--home", type=pathlib.Path, default=pathlib.Path.home())
    cli.add_argument("--chrome-root", type=pathlib.Path)
    options = cli.parse_args()
    result = register_linux(options.host, options.chrome_extension, options.home,
                            options.chrome_root or options.home / ".config/google-chrome")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
