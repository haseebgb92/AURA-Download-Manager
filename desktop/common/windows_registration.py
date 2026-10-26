"""Per-user Windows registration for AURA's authorized native browser bridge."""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys

HOST = "com.advertpreneur.aura"
FIREFOX_ID = "aura-download-manager@local"
CHROME_ID = re.compile(r"^[a-p]{32}$")


def get_matching_extensions(user_data: pathlib.Path, trusted_chrome: pathlib.Path) -> list[str]:
    """Only authorize IDs whose installed worker equals the bundled AURA worker."""
    reference = trusted_chrome / "worker.js"
    if not reference.is_file():
        return []
    trusted_bytes = reference.read_bytes()
    found = set()
    for prefs in user_data.glob("*/Preferences"):
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = data.get("extensions", {}).get("settings", {})
        for ident, info in entries.items():
            if not CHROME_ID.fullmatch(ident):
                continue
            path = info.get("path", "")
            if not path:
                continue
            installed = pathlib.Path(path)
            try:
                # Avoid an arbitrary extension gaining native rights by merely
                # copying AURA's name into its own manifest.
                manifest = json.loads((installed / "manifest.json").read_text(encoding="utf-8"))
                if manifest.get("name") != "AURA Download Manager" or "nativeMessaging" not in manifest.get("permissions", []):
                    continue
                if (installed / "worker.js").read_bytes() != trusted_bytes:
                    continue
                found.add(ident)
            except (OSError, ValueError):
                continue
    return sorted(found)


def register_windows(package_dir: pathlib.Path, app_dir: pathlib.Path, local_app_data: pathlib.Path) -> dict:
    """Idempotent user-only native messaging host installation; Windows only."""
    if os.name != "nt":
        return {"registered": False, "reason": "Windows registration required"}
    import winreg
    host = package_dir / "AURA-Native-Host.exe"
    if not host.is_file():
        return {"registered": False, "reason": "AURA native helper is missing"}
    app_dir.mkdir(parents=True, exist_ok=True)
    chrome_ids = get_matching_extensions(
        local_app_data / "Google/Chrome/User Data", package_dir / "chrome"
    )
    base = {
        "name": HOST,
        "description": "AURA Download Manager by Advertpreneur",
        "type": "stdio",
        "path": str(host.resolve()),
    }

    def write_manifest(file: pathlib.Path, payload: dict):
        file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def set_registry(key: str, path: pathlib.Path):
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_WRITE) as reg:
            winreg.SetValueEx(reg, "", 0, winreg.REG_SZ, str(path.resolve()))

    firefox = app_dir / f"{HOST}.firefox.json"
    write_manifest(firefox, {**base, "allowed_extensions": [FIREFOX_ID]})
    set_registry(rf"Software\Mozilla\NativeMessagingHosts\{HOST}", firefox)
    if chrome_ids:
        chrome = app_dir / f"{HOST}.chrome.json"
        write_manifest(chrome, {
            **base,
            "allowed_origins": [f"chrome-extension://{ident}/" for ident in chrome_ids],
        })
        set_registry(rf"Software\Google\Chrome\NativeMessagingHosts\{HOST}", chrome)
    return {"registered": True, "chrome_ids": chrome_ids, "firefox": True}
