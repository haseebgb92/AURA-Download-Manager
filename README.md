# AURA Download Manager

**AURA by Advertpreneur.** A clean, lightweight desktop download manager using **aria2** for direct HTTP(S) transfers. It supports a native GTK frontend on Linux, a Qt desktop frontend for Windows, and optional Chrome and Firefox browser handoff.

**Product website:** https://haseebgb92.github.io/AURA-Download-Manager/ (available after GitHub Pages is enabled and deployment succeeds)

## Updates and releases

**v0.6.1 Linux visual hotfix:** registers the bundled AURA icon as a valid user-level hicolor theme, rebuilds the icon cache, uses an absolute desktop launcher icon path, and strengthens the native GTK gradient surfaces. This corrects generic taskbar/menu icons and barely visible gradients on Linux Mint/Cinnamon. The Linux installer leaves download history, credentials, and existing transfer sessions intact.



Version **0.6.1** includes a built-in **Settings → AURA updates → Check for updates** control on Linux and Windows. It checks the official GitHub Releases API and compares version numbers in a background thread. The app can check automatically when launched (Linux: at most once daily; Windows: configurable at launch). If a newer stable version is found, **Get update** opens the official release details. Installation is deliberately user-controlled: **no silent file replacement, arbitrary code execution, or forced restarts**.

Official packages are published by the [tag-triggered release workflow](.github/workflows/release.yml). They include Windows ZIP, Linux source installer archive, and SHA256 checksums. Unsigned packages may trigger platform warnings.

## What is available

| Component | Status | Source |
| --- | --- | --- |
| Linux GTK desktop | Source included; derived from existing locally running app | `desktop/linux/` |
| Windows Qt desktop | New Windows packaging workflow; native Windows runtime not yet field-tested | `desktop/windows/` |
| Chrome browser extension | Manual link handoff with pairing UI | `chrome/` |
| Firefox browser extension | Manual link handoff with pairing UI | `firefox/` |
| Project website | Static GitHub Pages site | `docs/` |

### Linux

Requires Linux with GTK 3, Ayatana AppIndicator, `aria2c` and Python 3 GI bindings. On Debian/Ubuntu/Mint:

```bash
sudo apt install aria2 python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
bash scripts/install-linux.sh
```

**Installer behavior:** makes a timestamped backup of the existing `app.py`, installs GTK code and CSS, and creates a desktop launcher. It **does not** delete history or credentials.

After installing, quit any older AURA process from its system tray and relaunch the app to load updated code.

### Windows

The Windows desktop uses **PySide6** and aria2. The GitHub Actions [Windows build workflow](https://github.com/haseebgb92/AURA-Download-Manager/actions/workflows/windows-build.yml) bundles aria2 in the packaged app.

After a successful workflow run, download the `AURA-Download-Manager-Windows` artifact, unzip it, and run `AURA-Download-Manager.exe` from its extracted directory. This is an **unsigned build**, not a signed installer. Windows SmartScreen may warn; verify the artifact comes from this repository's workflow before running it.

For local development, install aria2 and Python 3.12, then:

```powershell
pip install -r requirements-windows.txt
python desktop/windows/app.py
```

The Windows version supports HTTP(S) downloads, queue status, pause/resume, history removal, Recycle Bin deletion, and extension handoff. Linux-specific `yt-dlp` / `ffmpeg` stream workflows are **not yet ported** to Windows.

### Browser extensions

Install the extension in Chrome using `chrome://extensions` > Developer mode > Load unpacked > choose `chrome/`. In Firefox load `firefox/manifest.json` temporarily via `about:debugging` (permanent installs require Mozilla signing).

Open the desktop AURA app **Settings > Browser extension pairing > Copy pairing code**. Click the extension toolbar icon, paste the code, and click **Save pairing**. The extension stores the code in local extension storage only, never in the repository. You can also add a URL from the popup or right-click a link and select **Download with AURA**.

Browser downloads are **not captured automatically**. No `downloads.onCreated` listener runs. Normal Chrome/Firefox downloads remain in the browser.

For Linux YouTube downloads, additional local `yt-dlp` and `ffmpeg` dependencies may be needed. Only download media you are authorized to access.

### Branding and third-party attribution

AURA Download Manager is developed by **Advertpreneur**. It uses aria2 as a separate local transfer engine. The [aria2 license and upstream attribution](third_party/aria2/README.md) are included with Windows binary packages. AURA's interface, branding, and product identity are distinct from the engine.

## Privacy and security

- Browser bridge binds to `127.0.0.1:18763`; aria2 RPC binds to `127.0.0.1:18764`.
- The bridge requires a randomly generated local pairing token for every request. It is saved in `~/.local/share/aura-download-manager/bridge.token` on Linux, under LocalAppData on Windows.
- **Never commit `bridge.token`, `aria2.secret`, cookies, or local session files.**
- Existing old extension builds contained a fixed token in source; **rotate the token before making any earlier commit history public**.
- The desktop app does not transfer files to any third-party cloud by itself; downloads connect to the user-provided server.

## Development

```bash
python3 -m py_compile desktop/linux/app.py desktop/windows/app.py
node --check chrome/worker.js
node --check chrome/popup.js
node --check firefox/worker.js
node --check firefox/popup.js
```

The website's interactive download table is **sample UI data**, not live download telemetry.

## Project contributions

Issues and pull requests are welcome. This repository does **not** yet declare an open-source license; viewing public source does not automatically grant reuse rights. A license may be added by the owner.
