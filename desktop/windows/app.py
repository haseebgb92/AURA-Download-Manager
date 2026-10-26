"""AURA Download Manager for Windows — PySide6 + aria2 desktop frontend."""
from __future__ import annotations
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QItemSelectionModel
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QSpinBox, QStyle, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QFileDialog
)

APP_DIR = pathlib.Path(os.getenv("LOCALAPPDATA") or pathlib.Path.home() / ".local/share") / "AURA-Download-Manager"
APP_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_DOWNLOADS = pathlib.Path.home() / "Downloads"
DEFAULT_DOWNLOADS.mkdir(exist_ok=True)
PORT, RPC_PORT = 18763, 18764

def private_secret(name: str) -> str:
    path = APP_DIR / name
    if not path.exists():
        value = secrets.token_urlsafe(32)
        with path.open("x", encoding="utf-8") as fp:
            fp.write(value)
        if os.name != "nt": path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip()

PAIRING_TOKEN = private_secret("bridge.token")
ARIA_SECRET = private_secret("aria2.secret")

def read_config() -> dict:
    path = APP_DIR / "config.json"
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}

CONFIG = read_config()
DOWNLOADS = pathlib.Path(CONFIG.get("downloads", str(DEFAULT_DOWNLOADS))).expanduser()

def rpc(method: str, params=None):
    payload = json.dumps({
        "jsonrpc": "2.0", "id": "aura",
        "method": "aria2." + method,
        "params": ["token:" + ARIA_SECRET] + (params or [])
    }).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{RPC_PORT}/jsonrpc", payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        result = json.load(response)
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "aria2 RPC error"))
    return result["result"]

def aria_executable() -> str:
    bundled = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent)) / "bin" / (
        "aria2c.exe" if os.name == "nt" else "aria2c"
    )
    if bundled.is_file(): return str(bundled)
    available = shutil.which("aria2c")
    if available: return available
    raise RuntimeError("aria2c is missing. Install aria2 or use the bundled Windows release.")

ENGINE = None
ENGINE_LOCK = threading.RLock()
def start_engine():
    with ENGINE_LOCK:
        return _start_engine_locked()

def _start_engine_locked():
    global ENGINE
    try:
        rpc("getVersion")
        return
    except Exception:
        pass
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    session = APP_DIR / "session.txt"
    session.touch(exist_ok=True)
    args = [
        aria_executable(), "--enable-rpc=true", "--rpc-listen-all=false",
        f"--rpc-listen-port={RPC_PORT}", f"--rpc-secret={ARIA_SECRET}",
        f"--dir={DOWNLOADS}", "--continue=true",
        "--max-connection-per-server=16", "--split=16",
        "--min-split-size=1M", "--max-concurrent-downloads=3",
        "--file-allocation=none", "--auto-file-renaming=true",
        "--allow-overwrite=false", f"--save-session={session}",
        "--save-session-interval=30", f"--input-file={session}",
        "--quiet=true"
    ]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt": kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    ENGINE = subprocess.Popen(args, **kwargs)
    import time
    for _ in range(40):
        try:
            rpc("getVersion")
            return
        except Exception:
            if ENGINE.poll() is not None: break
            time.sleep(0.1)
    raise RuntimeError("Could not start aria2 RPC engine; check whether port 18764 is already in use.")

def validate_url(value: str) -> str:
    url = urllib.parse.urlsplit(value)
    if url.scheme not in ("http", "https") or not url.hostname:
        raise ValueError("Only HTTP(S) download URLs are supported.")
    if url.username or url.password:
        raise ValueError("URLs with embedded credentials are not supported.")
    return value

def add_download(url: str) -> str:
    start_engine()
    return rpc("addUri", [[validate_url(url)]])

def brief_status() -> dict:
    start_engine()
    return {"ok": True, "app": "AURA Download Manager", "platform": sys.platform, "engine": "aria2"}

class Bridge(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def respond(self, code: int, data: dict):
        raw = json.dumps(data).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Aura-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.respond(200, {"ok": True})

    def do_GET(self):
        if self.headers.get("X-Aura-Token") != PAIRING_TOKEN:
            self.respond(403, {"ok": False, "error": "Not paired"}); return
        if self.path == "/status":
            try: self.respond(200, brief_status())
            except Exception as exc: self.respond(503, {"ok": False, "error": str(exc)})
        else: self.respond(404, {"ok": False, "error": "Unknown endpoint"})

    def do_POST(self):
        if self.headers.get("X-Aura-Token") != PAIRING_TOKEN:
            self.respond(403, {"ok": False, "error": "Not paired"}); return
        if self.path != "/add":
            self.respond(501, {"ok": False, "error": "This media format requires the Linux media backend."}); return
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n < 1 or n > 4096: raise ValueError("Invalid request length")
            data = json.loads(self.rfile.read(n))
            if data.get("intent") != "user": raise ValueError("Automatic browser capture is disabled")
            gid = add_download(data.get("url", ""))
            self.respond(200, {"ok": True, "gid": gid})
        except Exception as exc:
            self.respond(400, {"ok": False, "error": str(exc)})

class Snapshot(QThread):
    ready = Signal(object)
    failed = Signal(str)
    def __init__(self, include_history: bool, cache: list):
        super().__init__()
        self.include_history = include_history
        self.cache = cache
    def run(self):
        try:
            start_engine()
            active = rpc("tellActive")
            waiting = rpc("tellWaiting", [0, 500])
            stopped = rpc("tellStopped", [0, 500]) if self.include_history else self.cache
            self.ready.emit({"entries": active + waiting + stopped, "history": stopped,
                             "speed": sum(int(e.get("downloadSpeed") or 0) for e in active)})
        except Exception as exc: self.failed.emit(str(exc))

CSS = """
QMainWindow, QWidget#base {background:#f6f8fc;color:#26354d}
QWidget {font-family:'Segoe UI',sans-serif;font-size:12px}
QLabel#heading{font-size:23px;font-weight:750;color:#172b49}
QLabel#hint{color:#60728b}
QLabel#metric{font-size:17px;font-weight:700;color:#174ea6}
QPushButton{background:#fff;border:1px solid #dbe3ef;border-radius:8px;padding:9px 11px;color:#273955}
QPushButton:hover{background:#eaf2ff;border-color:#a8c5ee}
QPushButton:pressed{background:#d9eaff}
QPushButton:disabled{background:#f0f3f8;color:#99a6ba}
QPushButton#primary{background:#2563eb;color:#fff;border-color:#2563eb;font-weight:700}
QPushButton#primary:hover{background:#1d51c4}
QLineEdit, QSpinBox, QComboBox{background:#fff;border:1px solid #d7e0ec;border-radius:8px;padding:9px 11px;color:#26354d}
QLineEdit:focus, QSpinBox:focus{border:2px solid #2563eb}
QTableWidget{background:#fff;color:#243249;border:1px solid #e0e7f0;border-radius:10px;gridline-color:transparent;selection-background-color:#dfedff;selection-color:#1a457e}
QHeaderView::section{background:#f5f8fd;border:none;border-bottom:1px solid #e3eaf3;padding:10px;text-align:left;color:#63758d;font-weight:700}
QTabWidget::pane{border:0;background:transparent}
QTabBar::tab{padding:12px 18px;margin-right:8px;color:#63758d;border-bottom:2px solid transparent}
QTabBar::tab:selected{color:#2563eb;border-color:#2563eb;font-weight:700}
QMessageBox{background:#fff}
"""

def nice_size(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AURA Download Manager")
        self.resize(1140, 730)
        self.cache = []
        self.last_history = 0.
        self.worker = None
        self.status_by_gid = {}
        self.setStyleSheet(CSS)
        root = QWidget()
        root.setObjectName("base")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(16)
        title = QLabel("AURA Download Manager")
        title.setObjectName("heading")
        outer.addWidget(title)
        intro = QLabel("Fast parallel downloads, a cleaner queue, and explicit browser handoff.")
        intro.setObjectName("hint")
        outer.addWidget(intro)
        bar = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("Paste a direct HTTP or HTTPS download link…")
        self.url.returnPressed.connect(self.add_clicked)
        bar.addWidget(self.url, 1)
        add = self.button("Add download", QStyle.SP_DialogApplyButton, self.add_clicked, primary=True)
        bar.addWidget(add)
        outer.addLayout(bar)
        metrics = QHBoxLayout()
        self.metrics = {}
        for key, label in (("active","Active"),("complete","Completed"),("waiting","Queued"),("speed","Download speed")):
            frame = QFrame()
            frame.setStyleSheet("QFrame{background:white;border:1px solid #e4eaf2;border-radius:11px} QLabel{border:none}")
            area = QVBoxLayout(frame)
            label_widget = QLabel(label)
            label_widget.setObjectName("hint")
            value = QLabel("—")
            value.setObjectName("metric")
            area.addWidget(label_widget)
            area.addWidget(value)
            metrics.addWidget(frame, 1)
            self.metrics[key] = value
        outer.addLayout(metrics)
        actions = QHBoxLayout()
        self.pause_btn = self.button("Pause", QStyle.SP_MediaPause, lambda:self.selected_action("pause"))
        self.resume_btn = self.button("Resume", QStyle.SP_MediaPlay, lambda:self.selected_action("unpause"))
        self.select_btn = self.button("Select all", QStyle.SP_DialogYesButton, self.select_all)
        self.remove_btn = self.button("Remove history", QStyle.SP_DialogDiscardButton, self.remove_history)
        self.delete_btn = self.button("Move to Recycle Bin", QStyle.SP_TrashIcon, self.delete_files)
        for b in (self.pause_btn,self.resume_btn,self.select_btn,self.remove_btn,self.delete_btn):
            actions.addWidget(b)
        actions.addStretch()
        outer.addLayout(actions)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.apply_filter)
        outer.addWidget(self.tabs,1)
        for tabname in ("All downloads","Queued & paused","Completed"):
            page=QWidget(); layout=QVBoxLayout(page);layout.setContentsMargins(0,12,0,0)
            if not hasattr(self,'table'):
                self.table=QTableWidget(0,6)
                self.table.setHorizontalHeaderLabels(["File / URL","Status","Progress","Speed","Size","ID"])
                self.table.setColumnHidden(5,True)
                self.table.verticalHeader().hide()
                self.table.setShowGrid(False)
                self.table.setAlternatingRowColors(True)
                self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
                self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
                self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
                for i in range(1,5):self.table.horizontalHeader().setSectionResizeMode(i,QHeaderView.ResizeToContents)
                self.table.itemSelectionChanged.connect(self.update_actions)
            if tabname=="All downloads":
                layout.addWidget(self.table)
            else:
                # Other tabs share the same model; switching re-parents the table.
                pass
            self.tabs.addTab(page,tabname)
        settings=QWidget()
        sf=QFormLayout(settings)
        self.download_path=QLineEdit(str(DOWNLOADS))
        choose = self.button("Choose folder",QStyle.SP_DirOpenIcon,self.choose_folder)
        dirrow=QHBoxLayout();dirrow.addWidget(self.download_path);dirrow.addWidget(choose)
        dirbox=QWidget();dirbox.setLayout(dirrow)
        sf.addRow("Downloads folder",dirbox)
        self.parallel = QSpinBox();self.parallel.setRange(1,16);self.parallel.setValue(16)
        sf.addRow("Connections per file",self.parallel)
        self.concurrent=QSpinBox();self.concurrent.setRange(1,20);self.concurrent.setValue(3)
        sf.addRow("Concurrent downloads",self.concurrent)
        sf.addRow("",self.button("Apply settings",QStyle.SP_DialogApplyButton,self.save_settings,primary=True))
        sf.addRow("Browser extension",self.button("Copy pairing code",QStyle.SP_DialogSaveButton,self.copy_pairing))
        info=QLabel("Only explicitly submitted links are sent to AURA. Pairing codes remain on your computer.")
        info.setWordWrap(True);info.setObjectName("hint");sf.addRow("",info)
        self.tabs.addTab(settings,"Settings")
        self.label=QLabel("Starting download engine…")
        self.label.setObjectName("hint")
        outer.addWidget(self.label)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh);self.timer.start(2500)
        self.refresh()

    def button(self,text,icon,callback,primary=False):
        b=QPushButton(text)
        b.setIcon(self.style().standardIcon(icon))
        if primary:b.setObjectName("primary")
        b.clicked.connect(callback)
        return b

    def selected_gids(self):
        return list({self.table.item(i.row(),5).text()
                     for i in self.table.selectionModel().selectedRows()
                     if self.table.item(i.row(),5) is not None})

    def update_actions(self):
        selected=self.selected_gids()
        for btn in (self.pause_btn,self.resume_btn,self.remove_btn,self.delete_btn):
            btn.setEnabled(bool(selected))

    def select_all(self):self.table.selectAll()

    def choose_folder(self):
        chosen=QFileDialog.getExistingDirectory(self,"Choose downloads folder",str(DOWNLOADS))
        if chosen:self.download_path.setText(chosen)

    def copy_pairing(self):
        QApplication.clipboard().setText(PAIRING_TOKEN)
        self.label.setText("Pairing code copied. Paste it into the browser extension, then clear your clipboard.")

    def add_clicked(self):
        try:
            add_download(self.url.text().strip())
            self.url.clear()
            self.label.setText("Download added to queue.")
            self.refresh()
        except Exception as exc:self.label.setText("Could not add download: " + str(exc))

    def selected_action(self,method):
        count=0;skipped=0
        for gid in self.selected_gids():
            if self.status_by_gid.get(gid) not in (("active","waiting") if method=="pause" else ("paused",)):
                skipped+=1;continue
            try:rpc(method,[gid]);count+=1
            except Exception:skipped+=1
        self.label.setText(f"{count} updated, {skipped} skipped.")
        self.refresh()

    def remove_history(self):self.remove_selected(False)
    def delete_files(self):self.remove_selected(True)

    def remove_selected(self,with_files:bool):
        gids=self.selected_gids()
        if not gids:return
        if with_files:
            if any(self.status_by_gid.get(g) in ("active","waiting","paused") for g in gids):
                self.label.setText("Stop downloads before deleting files.");return
        answer=QMessageBox.question(self,"Confirm",(
            f"Move files for {len(gids)} download(s) to the Recycle Bin and clear history?"
            if with_files else f"Remove {len(gids)} download(s) from history? Files will be kept."
        ),QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
        if answer!=QMessageBox.Yes:return
        paths=[]
        try:
            if with_files:
                from send2trash import send2trash
            for gid in gids:
                item=rpc("tellStatus",[gid])
                if with_files:
                    for f in item.get("files",[]):
                        file=pathlib.Path(f.get("path",""))
                        if file.is_file() and not file.is_symlink() and file.parent.resolve()==DOWNLOADS.resolve():
                            paths.append(file)
                if item["status"] in ("active","waiting","paused"):
                    rpc("forceRemove",[gid])
                else:rpc("removeDownloadResult",[gid])
            rpc("saveSession")
            if with_files:
                for file in set(paths):send2trash(str(file))
            self.cache=[];self.last_history=0
            self.label.setText(f"Removed {len(gids)} history entries." + (f" Recycled {len(set(paths))} files." if with_files else " Files preserved."))
            self.refresh()
        except Exception as exc:self.label.setText("History action failed: "+str(exc))

    def save_settings(self):
        global DOWNLOADS
        try:
            path=pathlib.Path(self.download_path.text()).expanduser().resolve()
            path.mkdir(parents=True,exist_ok=True)
            rpc("changeGlobalOption",[{
                "dir":str(path),"split":str(self.parallel.value()),
                "max-connection-per-server":str(self.parallel.value()),
                "max-concurrent-downloads":str(self.concurrent.value())
            }])
            DOWNLOADS=path
            (APP_DIR/"config.json").write_text(json.dumps({"downloads":str(path)},indent=2),encoding="utf-8")
            self.label.setText("Settings applied and saved.")
        except Exception as exc:self.label.setText("Settings error: "+str(exc))

    def refresh(self):
        if self.worker is not None and self.worker.isRunning():return
        import time
        now=time.monotonic()
        include=(now-self.last_history)>10
        self.worker=Snapshot(include,self.cache)
        self.worker.ready.connect(lambda data:self.display_snapshot(data,include))
        self.worker.failed.connect(lambda error:self.label.setText("Engine: "+error))
        self.worker.start()

    def apply_filter(self,*_):
        if self.tabs.currentIndex() >= 3:
            self.table.setParent(None)
            return
        parent=self.tabs.widget(self.tabs.currentIndex())
        layout=parent.layout()
        if self.table.parent()!=parent:
            layout.addWidget(self.table)
        self.show_rows()

    def show_rows(self):
        mode=self.tabs.currentIndex()
        for row in range(self.table.rowCount()):
            status=self.table.item(row,1).text()
            hide=(mode==1 and status not in ("waiting","paused")) or (mode==2 and status!="complete")
            self.table.setRowHidden(row,hide)

    def display_snapshot(self,data,history_updated):
        import time
        if history_updated:
            self.cache=data["history"];self.last_history=time.monotonic()
        entries=data["entries"]
        selected=set(self.selected_gids())
        self.status_by_gid={item["gid"]:item["status"] for item in entries}
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(entries))
        for row,item in enumerate(entries):
            total=int(item.get("totalLength") or 0)
            completed=int(item.get("completedLength") or 0)
            speed=int(item.get("downloadSpeed") or 0)
            files=item.get("files") or []
            file_name=(pathlib.Path(files[0].get("path","")).name if files else "") or (
                next((u.get("uri","") for u in files[0].get("uris",[])),"") if files else item["gid"]
            )
            values=[file_name,item["status"],
                    f"{100*completed/total:.1f}%" if total else "—",
                    nice_size(speed)+"/s" if speed else "—",
                    nice_size(completed)+" / "+nice_size(total) if total else nice_size(completed),
                    item["gid"]]
            for col,value in enumerate(values):
                existing=self.table.item(row,col)
                if existing is None:self.table.setItem(row,col,QTableWidgetItem(value))
                elif existing.text()!=value:existing.setText(value)
        self.table.clearSelection()
        for row in range(self.table.rowCount()):
            if self.table.item(row,5).text() in selected:
                self.table.selectionModel().select(self.table.model().index(row,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
        self.table.setUpdatesEnabled(True)
        if self.tabs.currentIndex()<3:self.show_rows()
        self.metrics["active"].setText(str(sum(x["status"]=="active" for x in entries)))
        self.metrics["waiting"].setText(str(sum(x["status"]=="waiting" for x in entries)))
        self.metrics["complete"].setText(str(sum(x["status"]=="complete" for x in entries)))
        self.metrics["speed"].setText(nice_size(data["speed"])+"/s")
        self.update_actions()

def main():
    if '--self-test' in sys.argv:
        start_engine()
        assert rpc('getVersion').get('version')
        assert validate_url('https://example.org/example.zip')
        return 0
    ui_smoke='--ui-smoke' in sys.argv
    if ui_smoke:
        sys.argv.remove('--ui-smoke')
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QApplication(sys.argv)
    app.setApplicationName("AURA Download Manager")
    try:start_engine()
    except Exception as exc:
        QMessageBox.critical(None,"AURA startup failed",str(exc))
        return 1
    try:
        server=ThreadingHTTPServer(("127.0.0.1",PORT),Bridge)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
    except OSError as exc:
        QMessageBox.critical(None,"AURA browser bridge",f"Could not start local bridge: {exc}")
        return 1
    win=MainWindow()
    win.show()
    if ui_smoke:
        for index in (1,2,3,0):
            win.tabs.setCurrentIndex(index)
            app.processEvents()
        if win.worker is not None:
            win.worker.wait(15000)
        app.processEvents()
        server.shutdown()
        return 0
    code=app.exec()
    server.shutdown()
    return code

if __name__=="__main__":
    sys.exit(main())
