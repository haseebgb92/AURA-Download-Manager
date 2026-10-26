#!/usr/bin/python3
import os,json,secrets,subprocess,urllib.request,urllib.parse,threading,http.server,pathlib,time,shutil,sys,webbrowser
import gi
gi.require_version('Gtk','3.0');gi.require_version('AyatanaAppIndicator3','0.1')
from gi.repository import Gtk,GLib,Gdk,Gio,GdkPixbuf,AyatanaAppIndicator3 as Indicator
ROOT=pathlib.Path.home()/'.local/share/aura-download-manager';ROOT.mkdir(parents=True,exist_ok=True)
# Development layout and installed app both resolve the same update service.
COMMON=pathlib.Path(__file__).resolve().parents[1]/'common'
if COMMON.is_dir():sys.path.insert(0,str(COMMON))
from update_service import VERSION, RELEASES_URL, check_for_updates

TOKEN_FILE=ROOT/'bridge.token'
if not TOKEN_FILE.exists():TOKEN_FILE.write_text(secrets.token_urlsafe(32));TOKEN_FILE.chmod(0o600)
TOKEN=TOKEN_FILE.read_text().strip(); PORT=18763
SECRET_FILE=ROOT/'aria2.secret'
if not SECRET_FILE.exists():SECRET_FILE.write_text(secrets.token_hex(24));SECRET_FILE.chmod(0o600)
SECRET=SECRET_FILE.read_text().strip()
DOWNLOADS=pathlib.Path.home()/'Downloads'
DAEMON=None
APP_INSTANCE=None

def rpc(method,params=None):
    data=json.dumps({'jsonrpc':'2.0','id':'aura','method':'aria2.'+method,'params':['token:'+SECRET]+(params or [])}).encode()
    req=urllib.request.Request('http://127.0.0.1:18764/jsonrpc',data,{'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=2) as r:res=json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail=json.loads(e.read().decode()).get('error',{})
            raise RuntimeError(detail.get('message',str(e))) from e
        except (ValueError,AttributeError):raise RuntimeError(f'aria2 returned HTTP {e.code}') from e
    if 'error' in res:raise Exception(res['error']['message'])
    return res['result']

def ensure_daemon():
    global DAEMON
    try:rpc('getVersion');return
    except Exception:pass
    DAEMON=subprocess.Popen(['aria2c','--enable-rpc=true','--rpc-listen-all=false','--rpc-listen-port=18764','--rpc-secret='+SECRET,'--dir='+str(DOWNLOADS),'--continue=true','--max-connection-per-server=16','--split=16','--min-split-size=1M','--max-concurrent-downloads=3','--file-allocation=none','--auto-file-renaming=true','--allow-overwrite=false','--save-session='+str(ROOT/'session.txt'),'--save-session-interval=30','--input-file='+str(ROOT/'session.txt'),'--daemon=false','--quiet=true'],stdout=subprocess.DEVNULL,stderr=(ROOT/'aria2.log').open('ab'),start_new_session=True)
    for i in range(20):
        try:rpc('getVersion');return
        except Exception:time.sleep(.15)
    raise RuntimeError('aria2 startup failed; see '+str(ROOT/'aria2.log'))

def add(url):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.netloc:raise ValueError('Only http/https URLs are supported')
    ensure_daemon();return rpc('addUri',[[url]])

STREAMS={}
def add_stream(url,kind):
    parsed=urllib.parse.urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.netloc:raise ValueError('Invalid stream URL')
    if parsed.hostname in ('localhost','127.0.0.1','::1') or parsed.hostname.endswith('.local'):
        # Local samples are allowed for test; never pass file: or arbitrary schemes.
        pass
    if kind not in ('hls','dash'):raise ValueError('Unsupported stream type')
    extension=pathlib.Path(parsed.path).suffix.lower()
    if (kind=='hls' and extension!='.m3u8') or (kind=='dash' and extension!='.mpd'):
        raise ValueError('Not a recognized manifest URL')
    name='AURA-Stream-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3)+'.mp4'
    output=DOWNLOADS/name
    log=(ROOT/'stream.log').open('ab')
    command=['ffmpeg','-nostdin','-hide_banner','-loglevel','warning','-y','-protocol_whitelist','file,http,https,tcp,tls,crypto','-i',url,'-map','0:v:0?','-map','0:a:0?','-c','copy','-movflags','+faststart',str(output)]
    proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    gid='stream-'+str(proc.pid)
    STREAMS[gid]={'proc':proc,'file':str(output),'url':url,'type':kind}
    return gid


YT_ENV={**os.environ,'PYTHONPATH':str(ROOT/'python312-deps') + (':' + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')}
YOUTUBE_JOBS={}
YT_LOCK=threading.Lock()
def youtube_url(url):
    u=urllib.parse.urlparse(url)
    return u.scheme=='https' and (u.hostname or '').lower() in ('youtube.com','www.youtube.com','m.youtube.com','youtu.be','www.youtu.be') and bool(u.path.strip('/'))
def yt_formats(url):
    if not youtube_url(url):raise ValueError('Only public YouTube URLs are supported')
    result=subprocess.run([str(pathlib.Path.home()/'.local/bin/yt-dlp'),'--cookies-from-browser','chrome','--js-runtimes','node','--no-playlist','--skip-download','--dump-single-json',url],capture_output=True,text=True,timeout=30,env=YT_ENV)
    if result.returncode:raise ValueError(result.stderr.strip()[-350:] or 'Cannot inspect this video')
    info=json.loads(result.stdout)
    heights=sorted({int(f['height']) for f in info.get('formats',[]) if f.get('height') and f.get('vcodec')!='none'},reverse=True)
    return {'title':info.get('title','YouTube video'),'qualities':[str(x) for x in heights if x<=4320],'audio':True}
def yt_add(url,quality):
    if not youtube_url(url):raise ValueError('Invalid YouTube URL')
    if quality!='audio' and (not str(quality).isdigit() or int(quality)>4320 or int(quality)<144):raise ValueError('Invalid quality')
    code='bestaudio/best' if quality=='audio' else f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
    gid='yt-'+secrets.token_hex(8)
    job={'gid':gid,'status':'waiting','title':'YouTube download','percent':0,'quality':quality,'file':'','error':''}
    with YT_LOCK:YOUTUBE_JOBS[gid]=job
    def worker():
        cmd=[str(pathlib.Path.home()/'.local/bin/yt-dlp'),'--cookies-from-browser','chrome','--js-runtimes','node','--no-playlist','--newline','--progress','-f',code,'--merge-output-format','mp4','-o',str(DOWNLOADS/'%(title).180B [%(id)s].%(ext)s'),url]
        with YT_LOCK:job['status']='active'
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True,env=YT_ENV)
        with YT_LOCK:job['proc']=proc
        import re
        for line in proc.stdout:
            m=re.search(r'\[download\]\s+([0-9.]+)%',line)
            if m:
                with YT_LOCK:job['percent']=float(m.group(1))
            if line.startswith('[download] Destination:'):
                with YT_LOCK:job['file']=line.partition('Destination:')[2].strip()
            if line.startswith('[Merger] Merging formats into'):
                with YT_LOCK:job['file']=line.partition('into')[2].strip().strip('"')
            if 'ERROR:' in line or 'HTTP Error 429' in line:
                with YT_LOCK:job['error']=line.strip()[-250:]
        proc.wait()
        with YT_LOCK:
            job['status']='complete' if proc.returncode==0 else 'error'
            job['percent']=100 if proc.returncode==0 else job['percent']
            if proc.returncode!=0 and ('not a bot' in job['error'].lower() or '429' in job['error']):
                job['error']='YouTube requires sign-in verification (HTTP 429). Download not available without authorized browser authentication.'
            elif proc.returncode!=0 and not job['error']:
                job['error']='yt-dlp could not retrieve this video; check video availability and AURA logs.'
    threading.Thread(target=worker,daemon=True).start()
    return gid

class Bridge(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_OPTIONS(self):
        self.send_response(204);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Headers','X-Aura-Token, Content-Type');self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS');self.end_headers()
    def do_GET(self):
        if self.path not in ('/yt/jobs','/status','/show') or self.headers.get('X-Aura-Token')!=TOKEN:
            self.send_response(403);self.end_headers();return
        if self.path=='/status':
            data=json.dumps({'ok':True,'app':'AURA Download Manager','platform':'linux'}).encode()
        elif self.path=='/show':
            if APP_INSTANCE is None:
                self.send_response(503);self.end_headers();return
            GLib.idle_add(APP_INSTANCE.show)
            data=json.dumps({'ok':True,'shown':True}).encode()
        else:
            with YT_LOCK:
                data=json.dumps({'ok':True,'jobs':[{k:v for k,v in x.items() if k!='proc'} for x in YOUTUBE_JOBS.values()]}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.path not in ('/add','/stream','/yt/formats','/yt/add') or self.headers.get('X-Aura-Token')!=TOKEN:
            self.send_response(403);self.end_headers();return
        try:
            n=int(self.headers.get('Content-Length',0))
            if not 0<n<=4096:raise ValueError('Invalid length')
            payload=json.loads(self.rfile.read(n));url=payload.get('url','')
            if self.path=='/add' and payload.get('intent')!='user':
                raise ValueError('Automatic browser capture disabled; choose Download with AURA explicitly')
            if self.path=='/yt/formats':
                response=json.dumps({'ok':True,**yt_formats(url)}).encode()
            else:
                gid=yt_add(url,str(payload.get('quality','720'))) if self.path=='/yt/add' else add_stream(url,payload.get('kind')) if self.path=='/stream' else add(url)
                response=json.dumps({'ok':True,'gid':gid}).encode()
            status=200
        except Exception as e:
            response=json.dumps({'ok':False,'error':str(e)}).encode();status=400
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Content-Length',str(len(response)));self.end_headers();self.wfile.write(response)

class App:
    def __init__(self):
        ensure_daemon()
        GLib.set_prgname('aura-download-manager')
        GLib.set_application_name('AURA Download Manager')
        style=Gtk.CssProvider()
        style.load_from_path(str(ROOT/'style.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),style,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win=Gtk.Window(title='AURA Download Manager')
        self.win.set_wmclass('aura-download-manager','AURA Download Manager')
        app_icon=pathlib.Path.home()/'.local/share/icons/hicolor/256x256/apps/aura-download-manager.png'
        if app_icon.is_file():
            self.win.set_icon_from_file(str(app_icon))
        else:
            self.win.set_icon_name('aura-download-manager')
        self.win.set_default_size(1230,790)
        self.win.set_size_request(930,580)
        self.win.get_style_context().add_class('aura-manager')
        self.win.connect('delete-event',self.hide)
        self.win.connect('key-press-event',self.on_global_key)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        self.win.add(outer)

        header=Gtk.Box(spacing=12)
        header.get_style_context().add_class('aura-topbar')
        outer.pack_start(header,False,False,0)
        icon_path=pathlib.Path.home()/'.local/share/icons/hicolor/256x256/apps/aura-download-manager.png'
        icon=(Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path),52,52,True))
              if icon_path.is_file() else Gtk.Image.new_from_icon_name('folder-download-symbolic',Gtk.IconSize.DIALOG))
        icon.get_style_context().add_class('aura-mark')
        header.pack_start(icon,False,False,0)
        brand=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=0)
        header.pack_start(brand,True,True,0)
        wordmark=Gtk.Label(label='AURA')
        wordmark.set_xalign(0)
        wordmark.get_style_context().add_class('aura-brand')
        brand.pack_start(wordmark,False,False,0)
        product=Gtk.Label(label='Download Manager  •  by Advertpreneur')
        product.set_xalign(0)
        product.get_style_context().add_class('aura-product')
        brand.pack_start(product,False,False,0)
        status_badge=Gtk.Label(label='●  Ready')
        status_badge.get_style_context().add_class('aura-ready')
        header.pack_end(status_badge,False,False,0)
        self.connection_badge=status_badge
        folder=Gtk.Button()
        folder.add(Gtk.Image.new_from_icon_name('folder-open-symbolic',Gtk.IconSize.BUTTON))
        folder.get_style_context().add_class('aura-icon')
        folder.set_tooltip_text('Open Downloads folder')
        folder.get_accessible().set_name('Open Downloads folder')
        folder.connect('clicked',lambda *_:subprocess.Popen(['xdg-open',str(DOWNLOADS)]))
        header.pack_end(folder,False,False,0)

        workspace=Gtk.Box(spacing=0)
        workspace.get_style_context().add_class('aura-main')
        outer.pack_start(workspace,True,True,0)
        sidebar=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=7)
        sidebar.get_style_context().add_class('aura-sidebar')
        sidebar.set_size_request(199,-1)
        workspace.pack_start(sidebar,False,False,0)
        nav_title=Gtk.Label(label='WORKSPACE')
        nav_title.set_xalign(0)
        nav_title.set_margin_start(12)
        nav_title.set_margin_bottom(10)
        nav_title.get_style_context().add_class('aura-sidebar-heading')
        sidebar.pack_start(nav_title,False,False,0)
        self.view_filter='all'
        self.nav_buttons={}
        def nav(icon_name,caption,mode):
            button=Gtk.Button()
            content=Gtk.Box(spacing=13)
            image=Gtk.Image.new_from_icon_name(icon_name,Gtk.IconSize.BUTTON)
            content.pack_start(image,False,False,0)
            label=Gtk.Label(label=caption);label.set_xalign(0)
            content.pack_start(label,True,True,0)
            button.add(content)
            button.get_style_context().add_class('aura-nav')
            button.set_tooltip_text(caption)
            button.connect('clicked',lambda *_:self.set_view(mode))
            sidebar.pack_start(button,False,False,0)
            self.nav_buttons[mode]=button
        nav('folder-download-symbolic','All downloads','all')
        nav('view-list-symbolic','Queue & paused','waiting')
        nav('emblem-default-symbolic','Completed','complete')
        gap=Gtk.Box()
        sidebar.pack_start(gap,True,True,0)
        bottom_label=Gtk.Label(label='PREFERENCES')
        bottom_label.set_xalign(0)
        bottom_label.set_margin_start(12)
        bottom_label.set_margin_bottom(6)
        bottom_label.get_style_context().add_class('aura-sidebar-heading')
        sidebar.pack_start(bottom_label,False,False,0)
        nav('emblem-system-symbolic','Settings','settings')
        engine_note=Gtk.Label(label=f'An Advertpreneur product\nVersion {VERSION}')
        engine_note.set_xalign(0)
        engine_note.set_margin_top(12)
        engine_note.set_margin_start(12)
        engine_note.get_style_context().add_class('aura-sidebar-note')
        sidebar.pack_start(engine_note,False,False,0)

        main=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=17)
        main.get_style_context().add_class('aura-content')
        content_scroll=Gtk.ScrolledWindow()
        content_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC)
        content_scroll.add(main)
        workspace.pack_start(content_scroll,True,True,0)
        self.main=main
        self.download_area=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
        main.pack_start(self.download_area,True,True,0)

        intro=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5)
        self.download_area.pack_start(intro,False,False,0)
        intro_title=Gtk.Label(label='Download overview')
        intro_title.set_xalign(0)
        intro_title.get_style_context().add_class('aura-section-title')
        intro.pack_start(intro_title,False,False,0)
        intro_hint=Gtk.Label(label='Your transfers, progress and files — all in one place.')
        intro_hint.set_xalign(0)
        intro_hint.get_style_context().add_class('aura-description')
        intro.pack_start(intro_hint,False,False,0)

        stats=Gtk.Box(spacing=12)
        self.download_area.pack_start(stats,False,False,0)
        self.stat_labels={}
        for key,caption,icon_name in [('active','ACTIVE','media-playback-start-symbolic'),('completed','COMPLETED','emblem-default-symbolic'),('speed','TOTAL SPEED','network-transmit-symbolic'),('queued','IN QUEUE','view-list-symbolic')]:
            card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=9)
            card.get_style_context().add_class('aura-metric')
            stats.pack_start(card,True,True,0)
            topline=Gtk.Box(spacing=9)
            i=Gtk.Image.new_from_icon_name(icon_name,Gtk.IconSize.BUTTON)
            i.get_style_context().add_class('aura-metric-icon')
            topline.pack_start(i,False,False,0)
            label=Gtk.Label(label=caption)
            label.set_xalign(0)
            label.get_style_context().add_class('aura-stat-label')
            topline.pack_start(label,False,False,0)
            card.pack_start(topline,False,False,0)
            number=Gtk.Label(label='0')
            number.set_xalign(0)
            number.get_style_context().add_class('aura-stat-number')
            card.pack_start(number,False,False,0)
            self.stat_labels[key]=number

        toolbar=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6)
        toolbar.get_style_context().add_class('aura-toolbar')
        self.download_area.pack_start(toolbar,False,False,0)
        urlrow=Gtk.Box(spacing=10)
        toolbar.pack_start(urlrow,False,False,0)
        self.entry=Gtk.Entry()
        self.entry.set_placeholder_text('Paste an HTTP or HTTPS download link…')
        self.entry.connect('activate',self.on_add)
        urlrow.pack_start(self.entry,True,True,0)
        add_button=Gtk.Button()
        add_inner=Gtk.Box(spacing=9)
        add_inner.pack_start(Gtk.Image.new_from_icon_name('list-add-symbolic',Gtk.IconSize.BUTTON),False,False,0)
        add_inner.pack_start(Gtk.Label(label='Add download'),False,False,0)
        add_button.add(add_inner)
        add_button.get_style_context().add_class('aura-primary')
        add_button.connect('clicked',self.on_add)
        urlrow.pack_start(add_button,False,False,0)
        hint=Gtk.Label(label='Browser extensions send only links you explicitly choose.')
        hint.set_xalign(0)
        hint.set_margin_start(3)
        hint.get_style_context().add_class('aura-toolbar-hint')
        toolbar.pack_start(hint,False,False,0)

        actions=Gtk.Box(spacing=7)
        self.download_area.pack_start(actions,False,False,0)
        self.action_buttons={}
        controls=[
            ('pause','media-playback-pause-symbolic','Pause',lambda *_:self.action('pause')),
            ('resume','media-playback-start-symbolic','Resume',lambda *_:self.action('unpause')),
            ('select','edit-select-all-symbolic','Select all',lambda *_:self.select_all_visible()),
            ('remove','edit-clear-symbolic','Remove history',lambda *_:self.bulk_remove()),
            ('failed','dialog-error-symbolic','Clear failed',lambda *_:self.bulk_remove(failed_only=True)),
            ('delete','user-trash-symbolic','Move to Trash',lambda *_:self.bulk_remove(delete_files=True)),
        ]
        for key,icon_name,caption,callback in controls:
            button=Gtk.Button()
            inner=Gtk.Box(spacing=7)
            inner.pack_start(Gtk.Image.new_from_icon_name(icon_name,Gtk.IconSize.BUTTON),False,False,0)
            inner.pack_start(Gtk.Label(label=caption),False,False,0)
            button.add(inner)
            if key in ('remove','failed','delete'):button.get_style_context().add_class('aura-soft')
            if key=='delete':button.get_style_context().add_class('aura-danger')
            button.set_tooltip_text('Moves completed files to Trash after confirmation' if key=='delete' else caption)
            button.connect('clicked',callback)
            actions.pack_start(button,False,False,0)
            self.action_buttons[key]=button

        list_card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        list_card.get_style_context().add_class('aura-card')
        self.download_area.pack_start(list_card,True,True,0)
        panel_top=Gtk.Box(spacing=12)
        list_card.pack_start(panel_top,False,False,0)
        title_group=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=3)
        panel_top.pack_start(title_group,True,True,0)
        self.listhead=Gtk.Label(label='All downloads')
        self.listhead.set_xalign(0)
        self.listhead.get_style_context().add_class('aura-panel-title')
        title_group.pack_start(self.listhead,False,False,0)
        self.listcount=Gtk.Label(label='Select a transfer to manage it')
        self.listcount.set_xalign(0)
        self.listcount.get_style_context().add_class('aura-panel-subtitle')
        title_group.pack_start(self.listcount,False,False,0)
        self.search=Gtk.SearchEntry()
        self.search.set_placeholder_text('Search downloads')
        self.search.get_style_context().add_class('aura-search')
        self.search.connect('search-changed',self.on_search)
        panel_top.pack_end(self.search,False,False,0)

        self.store=Gtk.ListStore(str,str,str,str,str,str)
        self.filtered=self.store.filter_new()
        self.filtered.set_visible_func(self.is_visible)
        self.tree=Gtk.TreeView(model=self.filtered)
        self.tree.set_headers_visible(True)
        self.tree.set_enable_search(False)
        self.tree.set_rubber_banding(True)
        self.tree.set_grid_lines(Gtk.TreeViewGridLines.NONE)
        def text_column(title,index,width,expand=False):
            renderer=Gtk.CellRendererText()
            renderer.set_property('xpad',12)
            renderer.set_property('ypad',13)
            if index==0:
                renderer.set_property('ellipsize',3)
                renderer.set_property('weight',600)
            column=Gtk.TreeViewColumn(title,renderer,text=index)
            column.set_resizable(True)
            column.set_min_width(width)
            column.set_expand(expand)
            self.tree.append_column(column)
        # Render recognizable file-type icons, not just filenames.
        self._mime_icons={}
        file_col=Gtk.TreeViewColumn('FILE NAME')
        file_col.set_resizable(True)
        file_col.set_min_width(225)
        file_col.set_expand(True)
        file_cell=Gtk.CellRendererPixbuf()
        file_cell.set_property('xpad',8)
        file_cell.set_property('ypad',9)
        file_col.pack_start(file_cell,False)
        def file_icon(column,cell,model,itr,data=None):
            filename=model[itr][0]
            suffix=pathlib.Path(filename).suffix.casefold()
            icon_name=self._mime_icons.get(suffix)
            if not icon_name:
                mime,_=Gio.content_type_guess(filename,None)
                themed=Gio.content_type_get_icon(mime)
                names=themed.get_names() if isinstance(themed,Gio.ThemedIcon) else []
                icons=Gtk.IconTheme.get_default()
                icon_name=next((n for n in names if icons.has_icon(n)),'text-x-generic-symbolic')
                self._mime_icons[suffix]=icon_name
            cell.set_property('icon-name',icon_name)
        file_col.set_cell_data_func(file_cell,file_icon)
        filename_cell=Gtk.CellRendererText()
        filename_cell.set_property('xpad',6)
        filename_cell.set_property('ypad',13)
        filename_cell.set_property('ellipsize',3)
        filename_cell.set_property('weight',600)
        file_col.pack_start(filename_cell,True)
        file_col.add_attribute(filename_cell,'text',0)
        self.tree.append_column(file_col)
        status_renderer=Gtk.CellRendererText()
        status_renderer.set_property('xpad',12)
        status_renderer.set_property('ypad',13)
        status_col=Gtk.TreeViewColumn('STATUS',status_renderer,text=1)
        status_col.set_min_width(105)
        def status_data(column,cell,model,itr,data=None):
            state=model[itr][1]
            colors={'active':'#3666ca','complete':'#17866a','waiting':'#997328','paused':'#956eb7','error':'#b4495a','removed':'#8b98ae'}
            cell.set_property('foreground',colors.get(state,'#68778f'))
            cell.set_property('weight',700)
            cell.set_property('text',state.capitalize())
        status_col.set_cell_data_func(status_renderer,status_data)
        self.tree.append_column(status_col)
        progress_renderer=Gtk.CellRendererProgress()
        progress_renderer.set_property('xpad',12)
        progress_renderer.set_property('ypad',11)
        progress_col=Gtk.TreeViewColumn('PROGRESS',progress_renderer)
        progress_col.set_min_width(145)
        def progress_data(column,cell,model,itr,data=None):
            value=model[itr][2]
            try:amount=max(0,min(100,int(float(value.rstrip('%')))))
            except (TypeError,ValueError):amount=0
            cell.set_property('value',amount)
            cell.set_property('text',value)
        progress_col.set_cell_data_func(progress_renderer,progress_data)
        self.tree.append_column(progress_col)
        text_column('SPEED',3,105)
        text_column('SIZE',4,160)
        self.tree.set_tooltip_text('Select multiple transfers, then use the toolbar. Trash removes local files only after confirmation.')
        self.tree.connect('button-press-event',self.on_row_click)
        self.tree.connect('key-press-event',self.on_list_key)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.get_selection().connect('changed',self.selection_changed)
        self.tree.get_selection().set_select_function(lambda selection,model,path,selected,data:True,None)
        self.delete_column=Gtk.TreeViewColumn('REMOVE')
        pix=Gtk.CellRendererPixbuf()
        pix.set_property('icon-name','user-trash-symbolic')
        pix.set_property('xpad',16)
        pix.set_property('ypad',12)
        self.delete_column.pack_start(pix,False)
        self.delete_column.set_fixed_width(82)
        self.tree.append_column(self.delete_column)
        self.scroll=Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.AUTOMATIC,Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_min_content_height(180)
        self.scroll.get_style_context().add_class('aura-table-wrap')
        self.scroll.add(self.tree)
        list_card.pack_start(self.scroll,True,True,0)
        self.empty=Gtk.Label(label='No downloads here yet.\nPaste a link above to start your first transfer.')
        self.empty.set_justify(Gtk.Justification.CENTER)
        self.empty.get_style_context().add_class('aura-empty')
        list_card.pack_start(self.empty,True,True,0)
        self.details=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=7)
        self.details.get_style_context().add_class('aura-inspector')
        list_card.pack_start(self.details,False,False,0)
        self.detail_title=Gtk.Label(label='Selected transfer')
        self.detail_title.set_xalign(0)
        self.detail_title.set_ellipsize(3)
        self.detail_title.get_style_context().add_class('aura-panel-title')
        self.details.pack_start(self.detail_title,False,False,0)
        detail_row=Gtk.Box(spacing=12)
        self.details.pack_start(detail_row,False,False,0)
        self.detail_info=Gtk.Label(label='Download details')
        self.detail_info.set_xalign(0)
        self.detail_info.set_ellipsize(3)
        self.detail_info.get_style_context().add_class('aura-panel-subtitle')
        detail_row.pack_start(self.detail_info,True,True,0)
        self.reveal_button=Gtk.Button(label='Open folder')
        self.reveal_button.connect('clicked',self.reveal_selected)
        detail_row.pack_end(self.reveal_button,False,False,0)
        self.details.set_no_show_all(True)
        self.details.hide()
        self.entry_data={}

        self.settings_panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=17)
        main.pack_start(self.settings_panel,True,True,0)
        s_title=Gtk.Label(label='Download settings')
        s_title.set_xalign(0)
        s_title.get_style_context().add_class('aura-section-title')
        self.settings_panel.pack_start(s_title,False,False,0)
        caption=Gtk.Label(label='Tune performance and connect your browser. Changes take effect immediately.')
        caption.set_xalign(0)
        caption.get_style_context().add_class('aura-description')
        self.settings_panel.pack_start(caption,False,False,0)
        settings_group=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=20)
        settings_group.get_style_context().add_class('aura-settings-group')
        self.settings_panel.pack_start(settings_group,False,False,0)
        section=Gtk.Label(label='Transfer performance')
        section.set_xalign(0)
        section.get_style_context().add_class('aura-panel-title')
        settings_group.pack_start(section,False,False,0)
        grid=Gtk.Grid(column_spacing=30,row_spacing=17)
        settings_group.pack_start(grid,False,False,0)
        self.setting_controls={}
        options=[
            ('split','Connections per file (maximum 16)',1,16),
            ('max-concurrent-downloads','Simultaneous downloads',1,20),
            ('max-overall-download-limit','Total speed limit (KB/s, 0 = unlimited)',0,102400),
        ]
        for row,(key,label,lower,upper) in enumerate(options):
            lab=Gtk.Label(label=label)
            lab.set_xalign(0)
            lab.set_hexpand(True)
            grid.attach(lab,0,row,1,1)
            control=Gtk.SpinButton.new_with_range(lower,upper,1)
            control.set_numeric(True)
            control.set_size_request(140,-1)
            grid.attach(control,1,row,1,1)
            self.setting_controls[key]=control
        apply=Gtk.Button(label='Apply settings')
        apply.get_style_context().add_class('aura-primary')
        apply.connect('clicked',self.apply_settings)
        settings_group.pack_start(apply,False,False,0)
        pairing=Gtk.Box(spacing=15)
        pairing.get_style_context().add_class('aura-settings-group')
        self.settings_panel.pack_start(pairing,False,False,0)
        pair_info=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5)
        pairing.pack_start(pair_info,True,True,0)
        pair_label=Gtk.Label(label='Browser extension pairing')
        pair_label.set_xalign(0)
        pair_label.get_style_context().add_class('aura-panel-title')
        pair_info.pack_start(pair_label,False,False,0)
        pair_desc=Gtk.Label(label='Connect Chrome or Firefox with a code stored locally on this computer.')
        pair_desc.set_xalign(0)
        pair_desc.get_style_context().add_class('aura-settings-note')
        pair_info.pack_start(pair_desc,False,False,0)
        copy=Gtk.Button(label='Copy pairing code')
        copy.connect('clicked',self.copy_pairing)
        pairing.pack_end(copy,False,False,0)

        update_group=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        update_group.get_style_context().add_class('aura-settings-group')
        self.settings_panel.pack_start(update_group,False,False,0)
        update_title=Gtk.Label(label=f'AURA updates  •  Version {VERSION}')
        update_title.set_xalign(0)
        update_title.get_style_context().add_class('aura-panel-title')
        update_group.pack_start(update_title,False,False,0)
        update_row=Gtk.Box(spacing=12)
        update_group.pack_start(update_row,False,False,0)
        self.update_status=Gtk.Label(label='Check GitHub Releases for the latest AURA version.')
        self.update_status.set_xalign(0)
        self.update_status.set_line_wrap(True)
        self.update_status.get_style_context().add_class('aura-settings-note')
        update_row.pack_start(self.update_status,True,True,0)
        self.update_button=Gtk.Button(label='Check for updates')
        self.update_button.connect('clicked',self.check_updates)
        update_row.pack_end(self.update_button,False,False,0)
        self.get_update_button=Gtk.Button(label='Get update')
        self.get_update_button.get_style_context().add_class('aura-primary')
        self.get_update_button.connect('clicked',self.open_update)
        update_row.pack_end(self.get_update_button,False,False,0)
        self.get_update_button.set_no_show_all(True)
        self.get_update_button.hide()
        self.update_url=RELEASES_URL
        self.update_prefs_file=ROOT/'update-preferences.json'
        try:self.update_prefs=json.loads(self.update_prefs_file.read_text())
        except (OSError,ValueError):self.update_prefs={}
        self.auto_update=Gtk.CheckButton(label='Check for updates automatically (at most once daily)')
        self.auto_update.set_active(bool(self.update_prefs.get('enabled',True)))
        self.auto_update.connect('toggled',self.save_update_preference)
        update_group.pack_start(self.auto_update,False,False,0)
        update_hint=Gtk.Label(label='Updates are verified against the official releases. Installing is always your choice.')
        update_hint.set_xalign(0)
        update_hint.set_line_wrap(True)
        update_hint.get_style_context().add_class('aura-settings-note')
        update_group.pack_start(update_hint,False,False,0)

        foot=Gtk.Box(spacing=9)
        foot.get_style_context().add_class('aura-footbar')
        outer.pack_end(foot,False,False,0)
        status_icon=Gtk.Image.new_from_icon_name('emblem-ok-symbolic',Gtk.IconSize.MENU)
        foot.pack_start(status_icon,False,False,0)
        self.status=Gtk.Label(label='Ready to download')
        self.status.set_xalign(0)
        self.status.set_ellipsize(3)
        self.status.get_style_context().add_class('aura-footnote')
        foot.pack_start(self.status,True,True,0)
        foot_hint=Gtk.Label(label='Local transfers • No automatic browser capture')
        foot_hint.get_style_context().add_class('aura-footnote')
        foot.pack_end(foot_hint,False,False,0)

        self.ind=Indicator.Indicator.new('aura-download-manager','aura-download-manager',Indicator.IndicatorCategory.APPLICATION_STATUS)
        menu=Gtk.Menu()
        for title,cb in [('Show Download Manager',lambda *_:self.show()),('Open Downloads',lambda *_:subprocess.Popen(['xdg-open',str(DOWNLOADS)])),('Quit',lambda *_:self.quit())]:
            item=Gtk.MenuItem(label=title)
            item.connect('activate',cb)
            menu.append(item)
        menu.show_all()
        self.ind.set_menu(menu)
        self.ind.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',PORT),Bridge)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self._stopped_cache=[]
        self._stopped_at=0
        GLib.timeout_add(2500,self.refresh)
        self.settings_panel.set_no_show_all(True)
        self.settings_panel.hide()
        self.win.show_all()
        self.set_view('all')
        self.refresh()
        self.update_actions()
        if self.auto_update.get_active() and time.time()-float(self.update_prefs.get('last_check',0))>86400:
            GLib.timeout_add_seconds(3,self.auto_check_updates)

    def auto_check_updates(self):
        self.check_updates()
        return False

    def save_update_preference(self,*_):
        self.update_prefs['enabled']=self.auto_update.get_active()
        try:
            self.update_prefs_file.write_text(json.dumps(self.update_prefs))
            self.update_prefs_file.chmod(0o600)
        except OSError:
            self.status.set_text('Could not save update check preference.')

    def check_updates(self,*_):
        self.update_button.set_sensitive(False)
        self.update_status.set_text('Checking official releases…')
        self.get_update_button.hide()
        def worker():
            try:
                info=check_for_updates(VERSION)
                GLib.idle_add(self.update_check_result,info,None)
            except Exception as error:
                GLib.idle_add(self.update_check_result,None,str(error))
        threading.Thread(target=worker,name='aura-update-check',daemon=True).start()

    def update_check_result(self,info,error):
        self.update_button.set_sensitive(True)
        if not error:
            self.update_prefs['last_check']=time.time()
            self.save_update_preference()
        if error:
            self.update_status.set_text('Update check unavailable: '+error)
            return False
        if info.state=='available':
            self.update_status.set_text(f'Version {info.version} is available.')
            self.update_url=info.url
            self.get_update_button.set_no_show_all(False)
            self.get_update_button.show()
        elif info.state=='current':
            self.update_status.set_text(f'You have the latest published version (v{VERSION}).')
        else:
            self.update_status.set_text('No stable AURA release has been published yet.')
        return False

    def open_update(self,*_):
        webbrowser.open(self.update_url)

    def on_global_key(self,widget,event):
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval in (Gdk.KEY_f,Gdk.KEY_F):
                self.set_view('all')
                self.search.grab_focus()
                return True
            if event.keyval in (Gdk.KEY_l,Gdk.KEY_L):
                self.set_view('all')
                self.entry.grab_focus()
                return True
        return False

    def on_search(self,*_):
        if hasattr(self,'filtered'):
            self.filtered.refilter()
            self.update_list_state()

    def update_actions(self):
        if not hasattr(self,'action_buttons') or not hasattr(self,'tree'):
            return
        selected=bool(self.selected_gids())
        self.action_buttons['select'].set_sensitive(self.filtered.iter_n_children(None)>0)
        self.action_buttons['failed'].set_sensitive(any(row[1]=='error' for row in self.store))
        for key in ('pause','resume','remove','delete'):
            self.action_buttons[key].set_sensitive(selected)

    def update_list_state(self):
        if not hasattr(self,'filtered'):
            return
        count=self.filtered.iter_n_children(None)
        if self.view_filter!='settings':
            self.listcount.set_text(f'{count} visible  •  Select transfers for bulk actions')
            query=self.search.get_text().strip()
            empty_text=('No matches found. Try a different search.' if query else
                        'Your queue is clear.' if self.view_filter=='waiting' else
                        'No completed downloads yet.' if self.view_filter=='complete' else
                        'No downloads here yet.\nPaste a link above to start your first transfer.')
            self.empty.set_text(empty_text)
            self.scroll.set_visible(count>0)
            self.empty.set_visible(count==0)
        self.update_actions()

    def set_view(self,mode):
        self.view_filter=mode
        for key,button in self.nav_buttons.items():
            ctx=button.get_style_context()
            if key==mode:ctx.add_class('aura-nav-active')
            else:ctx.remove_class('aura-nav-active')
        if hasattr(self,'settings_panel'):
            if mode=='settings':
                self.download_area.hide();self.settings_panel.set_no_show_all(False);self.settings_panel.show_all();self.load_settings()
            else:
                self.settings_panel.hide();self.settings_panel.set_no_show_all(True);self.download_area.show_all()
                self.listhead.set_text({'all':'All downloads','waiting':'Queued & paused','complete':'Completed downloads'}[mode])
        if hasattr(self,'filtered'):
            self.filtered.refilter()
            self.update_list_state()
        if hasattr(self,'details'):self.update_inspector()
    def load_settings(self):
        try:
            opts=rpc('getGlobalOption')
            for key,ctrl in self.setting_controls.items():
                value=opts.get(key,'0')
                if key=='max-overall-download-limit':value=round(int(value)/1024) if str(value).isdigit() else 0
                ctrl.set_value(int(value))
        except Exception as e:self.status.set_text('Cannot load settings: '+str(e))
    def apply_settings(self,*_):
        try:
            values={key:str(int(ctrl.get_value())) for key,ctrl in self.setting_controls.items()}
            values['max-overall-download-limit']=str(int(values['max-overall-download-limit'])*1024)
            rpc('changeGlobalOption',[values]);self.status.set_text('Download settings saved to running aria2 engine.')
        except Exception as e:self.status.set_text('Could not save settings: '+str(e))
    def is_visible(self,model,itr,data=None):
        status=model[itr][1]
        category=(self.view_filter in ('all','settings')
                  or (self.view_filter=='waiting' and status in ('waiting','paused'))
                  or (self.view_filter=='complete' and status=='complete'))
        query=self.search.get_text().strip().casefold() if hasattr(self,'search') else ''
        return category and (not query or query in model[itr][0].casefold())
    def show(self):
        self.win.show_all()
        self.set_view(self.view_filter)
        self.win.present()
    def hide(self,*_):self.win.hide();return True
    def quit(self):self.server.shutdown();Gtk.main_quit()
    def copy_pairing(self,*_):
        clipboard=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(TOKEN,-1)
        clipboard.store()
        self.status.set_text('Pairing code copied. Paste it in the AURA extension popup, then clear your clipboard.')

    def selection_changed(self,*_):
        if not hasattr(self,'tree') or not hasattr(self,'status'):return
        count=len(self.selected_gids())
        if count:self.status.set_text(f'{count} selected • Pause, resume, remove history or move files to Trash')
        self.update_actions()
        self.update_inspector()

    def update_inspector(self):
        if not hasattr(self,'details'):return
        gids=self.selected_gids()
        if len(gids)!=1 or self.view_filter=='settings':
            self.details.hide()
            return
        gid=gids[0]
        item=self.entry_data.get(gid)
        if not item:
            self.details.hide()
            return
        files=item.get('files') or []
        path=pathlib.Path(files[0].get('path','')) if files and files[0].get('path') else None
        name=path.name if path else (self.store[0][0] if len(self.store)==1 else gid)
        total=int(item.get('totalLength') or 0)
        done=int(item.get('completedLength') or 0)
        speed=int(item.get('downloadSpeed') or 0)
        remaining=max(0,total-done)
        eta=('Calculating…' if not total else
             (f'{remaining//speed//60:d}m {remaining//speed%60:02d}s' if speed>0 else '—'))
        state=item.get('status','unknown').capitalize()
        self.detail_title.set_text(name)
        self.detail_info.set_text(
            f'{state}    •    {done/1048576:.1f} MB of {total/1048576:.1f} MB'
            f'    •    {speed/1048576:.2f} MB/s    •    ETA {eta}')
        self.reveal_button.set_sensitive(bool(path and path.parent.is_dir()))
        self.details.set_no_show_all(False)
        self.details.show_all()

    def reveal_selected(self,*_):
        gids=self.selected_gids()
        if len(gids)!=1:return
        item=self.entry_data.get(gids[0],{})
        files=item.get('files') or []
        if not files or not files[0].get('path'):return
        folder=pathlib.Path(files[0]['path']).parent
        if folder.is_dir():subprocess.Popen(['xdg-open',str(folder)])

    def copy_source(self,*_):
        gids=self.selected_gids()
        if len(gids)!=1:return
        item=self.entry_data.get(gids[0],{})
        files=item.get('files') or []
        uris=(files[0].get('uris') or []) if files else []
        url=next((u.get('uri') for u in uris if u.get('uri')),None)
        if not url:
            self.status.set_text('No source URL is available.')
            return
        clipboard=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(url,-1)
        clipboard.store()
        self.status.set_text('Source URL copied to clipboard.')

    def on_row_click(self,tree,event):
        hit=tree.get_path_at_pos(int(event.x),int(event.y))
        if not hit:return False
        path=hit[0]
        if event.button==3:
            if not tree.get_selection().path_is_selected(path):
                tree.get_selection().unselect_all()
                tree.get_selection().select_path(path)
            menu=Gtk.Menu()
            for caption,callback in [
                ('Pause transfer',lambda:self.action('pause')),
                ('Resume transfer',lambda:self.action('unpause')),
                ('Open containing folder',self.reveal_selected),
                ('Copy source URL',self.copy_source),
                ('Remove from history',lambda:self.bulk_remove()),
                ('Move downloaded file to Trash',lambda:self.bulk_remove(delete_files=True)),
            ]:
                item=Gtk.MenuItem(label=caption)
                item.connect('activate',lambda widget,action=callback:action())
                menu.append(item)
            menu.show_all()
            menu.popup_at_pointer(event)
            return True
        if event.button!=1 or hit[1]!=self.delete_column:return False
        try:self.bulk_remove(delete_files=True,gids=[self.filtered[path][5]])
        except Exception as e:self.status.set_text('Delete: '+str(e))
        return True

    def on_list_key(self,tree,event):
        if event.keyval==Gdk.KEY_Delete:
            self.bulk_remove(delete_files=True)
            return True
        return False

    def on_add(self,*_):
        url=self.entry.get_text().strip()
        try:add(url);self.entry.set_text('');self.status.set_text('Added download');self.refresh()
        except Exception as e:self.status.set_text('Error: '+str(e))
    def selected_gids(self):
        model,rows=self.tree.get_selection().get_selected_rows()
        return [model[path][5] for path in rows]

    def select_all_visible(self):
        self.tree.get_selection().select_all()
        count=len(self.selected_gids())
        self.status.set_text(f'{count} downloads selected. Remove Selected clears history only; Delete moves files to Trash.')

    def action(self,name):
        gids=self.selected_gids()
        if not gids:
            self.status.set_text('Select a download first.')
            return
        try:
            changed=0;skipped=0
            for gid in gids:
                if gid.startswith(('yt-','stream-')):skipped+=1;continue
                try:
                    status=rpc('tellStatus',[gid]).get('status')
                    if name=='pause' and status not in ('active','waiting') or name=='unpause' and status!='paused':skipped+=1;continue
                    rpc(name,[gid]);changed+=1
                except Exception:skipped+=1
            self.refresh()
            self.status.set_text(f'{changed} download(s) updated'+(f'; {skipped} not applicable' if skipped else '')+'.')
        except Exception as e:self.status.set_text(str(e))

    def delete_download(self,gid=None):
        self.bulk_remove(delete_files=True,gids=[gid] if gid else None)

    def bulk_remove(self,delete_files=False,failed_only=False,gids=None):
        # Clear Failed operates across the whole download history, regardless of the selected tab.
        # Remove Selected and Clear Failed never delete files from disk.
        if failed_only:
            try:
                entries=rpc('tellStopped',[0,10000])
                gids=[item['gid'] for item in entries if item['status']=='error']
            except Exception as error:
                self.status.set_text('Cannot list failed downloads: '+str(error));return
        elif gids is None:
            gids=self.selected_gids()
        gids=list(dict.fromkeys(gids))
        if not gids:
            self.status.set_text('No failed downloads to clear.' if failed_only else 'Select downloads first (or click Select All).')
            return
        items=[]
        for gid in gids:
            try:items.append(rpc('tellStatus',[gid]))
            except Exception:continue
        if not items:
            self.refresh();return
        paths=[]
        if delete_files:
            # Files can only be trashed after a download has stopped.
            if any(item['status'] in ('active','waiting','paused') for item in items):
                self.status.set_text('Stop downloads before using Delete. Remove Selected clears their history safely.')
                return
            for item in items:
                for f in item.get('files',[]):
                    path=f.get('path','')
                    if not path:continue
                    candidate=pathlib.Path(path)
                    if candidate.parent.resolve()==DOWNLOADS.resolve() and candidate.is_file() and not candidate.is_symlink():
                        paths.append(candidate)
            paths=list(dict.fromkeys(paths))
        title=('Clear '+str(len(items))+' failed downloads?' if failed_only else
               ('Delete '+str(len(items))+' downloads?' if delete_files else 'Remove '+str(len(items))+' history entries?'))
        dialog=Gtk.MessageDialog(transient_for=self.win,flags=0,
                                 message_type=Gtk.MessageType.WARNING if delete_files else Gtk.MessageType.QUESTION,
                                 buttons=Gtk.ButtonsType.NONE,text=title)
        if delete_files:
            detail=f'{len(items)} history entries will be removed. {len(paths)} existing file(s) in ~/Downloads will be moved to Trash.'
        else:
            detail='Only AURA history entries will be removed. Downloaded files will remain untouched.'
        dialog.format_secondary_text(detail)
        dialog.add_button('Cancel',Gtk.ResponseType.CANCEL)
        dialog.add_button('Delete' if delete_files else 'Clear History',Gtk.ResponseType.OK)
        confirmed=dialog.run()==Gtk.ResponseType.OK
        dialog.destroy()
        if not confirmed:return
        removed=0;errors=[]
        for item in items:
            gid=item['gid']
            try:
                if item['status'] in ('active','waiting','paused'):
                    rpc('forceRemove',[gid])
                    GLib.timeout_add(400,lambda g=gid:self.cleanup_stopped(g,0))
                else:
                    rpc('removeDownloadResult',[gid])
                removed+=1
            except Exception as error:errors.append(f'{gid}: {error}')
        if removed:
            try:rpc('saveSession')
            except Exception as error:errors.append('Could not persist cleared history: '+str(error))
        if delete_files:
            for f in paths:
                try:Gio.File.new_for_path(str(f)).trash(None)
                except Exception as error:errors.append(f'{f.name}: {error}')
        self.tree.get_selection().unselect_all()
        self._stopped_at=0
        self.refresh()
        self.status.set_text(f'{removed}/{len(items)} entries cleared'+
                             (f'; {len(paths)} files requested to Trash' if delete_files else '; files untouched')+
                             (f'; issues: {str(errors[0])[:130]}' if errors else ''))

    def cleanup_stopped(self,gid,attempt=0):
        try:
            status=rpc('tellStatus',[gid]).get('status')
            if status in ('removed','error','complete'):
                rpc('removeDownloadResult',[gid]);rpc('saveSession');self.refresh();return False
        except Exception as exc:
            # A missing gid means the history entry is already gone.
            if 'not found' in str(exc).lower():self.refresh();return False
        if attempt<15:
            GLib.timeout_add(400,lambda:self.cleanup_stopped(gid,attempt+1))
        else:self.status.set_text('Could not clear history; select the row and retry Delete.')
        return False
    def refresh(self):
        if getattr(self,'_refresh_pending',False):return True
        self._refresh_pending=True
        def load():
            try:
                active=rpc('tellActive')
                waiting=rpc('tellWaiting',[0,1000])
                now=time.monotonic()
                update_history=now-self._stopped_at>9
                stopped=rpc('tellStopped',[0,1000]) if update_history else self._stopped_cache
                with YT_LOCK:youtube=[dict(x) for x in YOUTUBE_JOBS.values()]
                GLib.idle_add(self.apply_snapshot,active+waiting+stopped,youtube,stopped,now,update_history)
            except Exception as e:GLib.idle_add(self.refresh_failed,str(e))
        threading.Thread(target=load,name='aura-status',daemon=True).start()
        return True

    def refresh_failed(self,message):
        self._refresh_pending=False
        self.connection_badge.set_text('●  Engine disconnected')
        self.connection_badge.get_style_context().add_class('aura-offline')
        self.status.set_text('Download engine: '+message)
        return False

    def apply_snapshot(self,entries,yt_entries,stopped,now,updated_history):
        try:
            self.connection_badge.set_text('●  Ready')
            self.connection_badge.get_style_context().remove_class('aura-offline')
            if updated_history:
                self._stopped_cache=stopped
                self._stopped_at=now
            self.entry_data={e['gid']:e for e in entries}
            current={row[5]:row for row in self.store}
            seen=set()
            for e in entries:
                gid=e['gid']
                seen.add(gid)
                total=int(e.get('totalLength') or 0)
                done=int(e.get('completedLength') or 0)
                speed=int(e.get('downloadSpeed') or 0)
                files=e.get('files') or []
                name=pathlib.Path(files[0].get('path','')).name if files else ''
                if not name:
                    name=(next((u.get('uri','') for u in files[0].get('uris',[]) if u.get('uri')),'') if files else gid)[:90]
                values=[name,e['status'],f'{done*100/total:.1f}%' if total else '0%',
                        f'{speed/1024:.0f} KB/s',f'{done/1048576:.1f} / {total/1048576:.1f} MB',gid]
                if gid in current:
                    for j,value in enumerate(values):
                        if current[gid][j]!=value:current[gid][j]=value
                else:self.store.append(values)
            for y in yt_entries:
                gid=y['gid']
                seen.add(gid)
                vals=[y['title']+' ('+y['quality']+')',y['status'],f"{y['percent']:.0f}%",
                      'yt-dlp',y.get('error','')[:60],gid]
                if gid in current:
                    for j,v in enumerate(vals):
                        if current[gid][j]!=v:current[gid][j]=v
                else:self.store.append(vals)
            for row in list(self.store):
                if row[5] not in seen:self.store.remove(row.iter)
            self.stat_labels['active'].set_text(str(sum(e['status']=='active' for e in entries)))
            self.stat_labels['completed'].set_text(str(sum(e['status']=='complete' for e in entries)))
            self.stat_labels['queued'].set_text(str(sum(e['status']=='waiting' for e in entries)))
            speed=sum(int(e.get('downloadSpeed') or 0) for e in entries)
            self.stat_labels['speed'].set_text(f'{speed/1048576:.1f} MB/s' if speed>=1048576 else f'{speed/1024:.0f} KB/s')
            self.filtered.refilter()
            self.update_list_state()
            self.update_inspector()
        except Exception as e:
            self.status.set_text('Render error: '+str(e))
        finally:self._refresh_pending=False
        return False

if __name__=='__main__':
    # Activate an already-running AURA instance instead of competing for bridge and RPC ports.
    try:
        request=urllib.request.Request(f'http://127.0.0.1:{PORT}/show',
                                       headers={'X-Aura-Token':TOKEN})
        with urllib.request.urlopen(request,timeout=1.2) as reply:
            if json.load(reply).get('shown'):
                sys.exit(0)
    except (urllib.error.URLError,ValueError,TimeoutError):
        pass
    APP_INSTANCE=App()
    Gtk.main()
