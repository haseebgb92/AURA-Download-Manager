"""Release-based update discovery for AURA (no silent remote code execution)."""
from __future__ import annotations
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

VERSION = "0.6.3"
REPOSITORY = "haseebgb92/AURA-Download-Manager"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_RESPONSE_BYTES = 512 * 1024
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class UpdateInfo:
    state: str  # available | current | unpublished
    version: str
    url: str
    notes: str = ""


def parse_version(value: str) -> tuple[int, int, int]:
    matched = _VERSION_RE.fullmatch(value.strip())
    if not matched:
        raise ValueError("Unsupported release version format")
    return tuple(map(int, matched.groups()))


def resolve_release(payload: dict, current_version: str = VERSION) -> UpdateInfo:
    if not isinstance(payload, dict):
        raise ValueError("Invalid release metadata")
    if payload.get("draft") or payload.get("prerelease"):
        return UpdateInfo("unpublished", current_version, RELEASES_URL)
    tag = str(payload.get("tag_name") or "")
    remote = parse_version(tag)
    current = parse_version(current_version)
    link = str(payload.get("html_url") or "")
    if not link.startswith(f"https://github.com/{REPOSITORY}/releases/tag/"):
        # Never use an untrusted release URL to navigate to another origin.
        link = RELEASES_URL
    notes = str(payload.get("body") or "")[:2500]
    return UpdateInfo("available" if remote > current else "current", tag.lstrip("v"), link, notes)


def check_for_updates(current_version: str = VERSION, *, timeout: float = 8) -> UpdateInfo:
    """Fetch GitHub Releases, bounded in time and size; never download or execute binaries."""
    request = urllib.request.Request(
        API_URL,
        headers={"User-Agent": f"AURA-Download-Manager/{current_version}",
                 "Accept": "application/vnd.github+json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            raw = reply.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("Release metadata is too large")
            return resolve_release(json.loads(raw), current_version)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return UpdateInfo("unpublished", current_version, RELEASES_URL)
        raise RuntimeError(f"GitHub returned HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise RuntimeError("Could not reach GitHub. Check your connection and retry.") from error
