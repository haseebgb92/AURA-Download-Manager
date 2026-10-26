#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
target="${HOME}/.local/share/aura-download-manager"
mkdir -p "$target" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/256x256/apps"
if ! command -v aria2c >/dev/null 2>&1; then
  echo "aria2 is required. Install it with your Linux package manager." >&2
  exit 1
fi
if ! /usr/bin/python3 -c 'import gi; gi.require_version("Gtk","3.0"); gi.require_version("AyatanaAppIndicator3","0.1"); from gi.repository import Gtk,AyatanaAppIndicator3' 2>/dev/null; then
  echo "Install python3-gi, gir1.2-gtk-3.0, and gir1.2-ayatanaappindicator3-0.1." >&2
  exit 1
fi
if [ -f "$target/app.py" ]; then
  cp "$target/app.py" "$target/app.py.backup-$(date +%Y%m%d-%H%M%S)"
fi
install -m 644 "$root/desktop/linux/app.py" "$target/app.py"
install -m 644 "$root/desktop/common/update_service.py" "$target/update_service.py"
install -m 644 "$root/desktop/linux/style.css" "$target/style.css"
install -m 644 "$root/assets/aura.png" "$HOME/.local/share/icons/hicolor/256x256/apps/aura-download-manager.png"
cat > "$HOME/.local/bin/aura-download-manager" <<'SCRIPT'
#!/bin/sh
exec /usr/bin/python3 "$HOME/.local/share/aura-download-manager/app.py" "$@"
SCRIPT
chmod +x "$HOME/.local/bin/aura-download-manager"
cat > "$HOME/.local/share/applications/aura-download-manager.desktop" <<EOF
[Desktop Entry]
Name=AURA Download Manager
Comment=AURA Download Manager by Advertpreneur
Exec=$HOME/.local/bin/aura-download-manager
Icon=aura-download-manager
Type=Application
Categories=Network;FileTransfer;
Terminal=false
StartupNotify=true
StartupWMClass=aura-download-manager
EOF
echo "Installed AURA. Relaunch it from your application menu."
