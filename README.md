# AURA Download Manager

**AURA by Advertpreneur.** A clean, lightweight desktop download manager using **aria2** for direct HTTP(S) transfers. It supports a native GTK frontend on Linux, a Qt desktop frontend for Windows, and optional Chrome and Firefox browser handoff.

**Product website:** https://haseebgb92.github.io/AURA-Download-Manager/ (available after GitHub Pages is enabled and deployment succeeds)

## Updates and releases

**v0.6.4 Automatic download capture:** Chrome and Firefox now listen for browser download events and automatically hand eligible HTTP(S) files to the AURA desktop manager. Images (PNG, JPEG, WebP, SVG, AVIF, GIF, HEIC and others), fonts, scripts, CSS and very small web assets stay in the browser. Private browsing, unsafe/download-warning files, and unsupported URL schemes are left untouched. A small toggle in the extension popup enables/disables automatic capture; default is on. Right-click **Download with AURA** works for links and images even when automatic capture is off.

The extension pauses an eligible download, sends only its URL through native messaging, and cancels/cleans the browser copy **only if AURA acknowledges that the job was queued**. If AURA is unavailable, it resumes the paused browser job. Downloads that require browser cookies, POST requests or private sessions may fail later in aria2; use the browser for those cases. Some very small downloads can finish before AURA can intercept them and will remain in Chrome/Firefox. Auto-capture works only when the desktop app is running.



**v0.6.3 Browser pairing upgrade:** no pairing codes. Chrome and Firefox use a browser-authorized native helper with a strict extension allowlist; the private desktop bridge token stays local. AURA automatically registers the helper on Linux installation and Windows startup (with the bundled helper). Reload an already installed extension once to pick up its new native-messaging permission. The previous browser-stored secret can be safely revoked.



**v0.6.2 Settings redesign:** the installed Linux GTK app now shows transfer performance beside compact browser-pairing and update panels. All settings fit at the supported 930 × 580 minimum window size, without requiring scrolling. Controls, update checks, saved settings, and AURA identity are preserved. Reopening the window no longer expands it unexpectedly.

**v0.6.1 Linux visual hotfix:** registers the bundled AURA icon as a valid user-level hicolor theme, rebuilds the icon cache, uses an absolute desktop launcher icon path, and strengthens the native GTK gradient surfaces. This corrects generic taskbar/menu icons and barely visible gradients on Linux Mint/Cinnamon. The Linux installer leaves download history, credentials, and existing transfer sessions intact.



Version **0.6.1** includes a built-in **Settings → AURA updates → Check for updates** control on Linux and Windows. It checks the official GitHub Releases API and compares version numbers in a background thread. The app can check automatically when launched (Linux: at most once daily; Windows: configurable at launch). If a newer stable version is found, **Get update** opens the official release details. Installation is deliberately user-controlled: **no silent file replacement, arbitrary code execution, or forced restarts**.

Official packages are published by the [tag-triggered release workflow](.github/workflows/release.yml). They include Windows ZIP, Linux source installer archive, and SHA256 checksums. Unsigned packages may trigger platform warnings.

## What is available

| Component | Status | Source |
| --- | --- | --- |
| Linux GTK desktop | Source included; derived from existing locally running app | `desktop/linux/` |
| Windows Qt desktop | New Windows packaging workflow; native Windows runtime not yet field-tested | `desktop/windows/` |
| Chrome browser extension | Automatic native connection; explicit link handoff | `chrome/` |
| Firefox browser extension | Automatic native connection; explicit link handoff | `firefox/` |
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

### Browser extensions — zero-code connection (v0.6.3)

**No pairing codes are required.** AURA uses standard Chrome/Firefox **Native Messaging**, with a per-user host manifest that authorizes only known AURA extension IDs. The browser never receives the local bridge credential.

**Linux:** Run `bash scripts/install-linux.sh` once. It registers Firefox's fixed extension ID and discovers Chrome's installed unpacked AURA extension ID from its actual profile path. Install/update the extension in `chrome://extensions` → Developer mode → Load unpacked → select `chrome/`, then click that extension's **Reload** icon once. Chrome's native messaging permission is required. The extension then connects automatically whenever desktop AURA is running. Firefox temporary add-on loading via `about:debugging` works similarly, while permanent distribution requires Mozilla signing.

**Windows:** The ZIP contains `AURA-Native-Host.exe`, a copy of the browser extensions, and the desktop executable. Launching the desktop app installs user-level native messaging manifests (no administrator access). Chrome installation is recognized when the unpacked extension's script matches the shipped AURA extension. After adding the unpacked Chrome extension, restart the desktop app once to register its browser ID, then reload the extension. Firefox uses its stable signed extension ID.

The extension popup automatically shows whether desktop AURA is connected; clicking **Check connection** is optional. With auto-capture enabled, eligible browser downloads transfer to AURA; images and excluded web assets remain in the browser. The popup toggle disables automatic capture without affecting the manual right-click action. Do not modify or share `bridge.token`.

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
