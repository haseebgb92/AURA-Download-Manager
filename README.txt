AURA Download Manager

Launch with Mint menu > AURA Download Manager.
Chrome setup: chrome://extensions > Developer mode > Load unpacked > choose Downloads/AURA-Download-Manager/chrome.
Firefox test setup: about:debugging#/runtime/this-firefox > Load Temporary Add-on > choose Downloads/AURA-Download-Manager/firefox/manifest.json. Firefox requires signing for permanent extensions.
Right-click any direct HTTP(S) link and choose Download with AURA.
Downloads go to ~/Downloads. Server must support ranges for parallel segments.
Browser extensions are manual context-menu capture only in this version; no interception of every browser download.

Version 0.4.2: Chrome automatic interception is removed. Chrome downloads stay in Chrome; use the right-click Download with AURA menu or the in-page media button to hand off explicitly. After updates, reload the unpacked extension at chrome://extensions. The AURA app supports Select All, Remove Selected (history only), and Clear Failed (history only). Delete moves existing files to Trash with confirmation.
