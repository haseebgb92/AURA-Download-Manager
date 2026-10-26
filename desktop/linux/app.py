#!/usr/bin/python3
import os,json,secrets,subprocess,urllib.request,urllib.parse,threading,http.server,pathlib,time,shutil
import gi
gi.require_version('Gtk','3.0');gi.require_version('AyatanaAppIndicator3','0.1')
from gi.repository import Gtk,GLib,Gdk,Gio,AyatanaAppIndicator3 as Indicator
ROOT=pathlib.Path.home()/'.local/share/aura-download-manager';ROOT.mkdir(parents=True,exist_ok=True)
TOKEN_FILE=ROOT/'bridge.token'
if not TOKEN_FILE.exists():TOKEN_FILE.write_text(secrets.token_urlsafe(32));TOKEN_FILE.chmod(0o600)
TOKEN=TOKEN_FILE.read_text().strip(); PORT=18763
SECRET_FILE=ROOT/'aria2.secret'
if not SECRET_FILE.exists():SECRET_FILE.write_text(secrets.token_hex(24));SECRET_FILE.chmod(0o600)
SECRET=SECRET_FILE.read_text().strip()
DOWNLOADS=pathlib.Path.home()/'Downloads'
DAEMON=None

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
        if self.path not in ('/yt/jobs','/status') or self.headers.get('X-Aura-Token')!=TOKEN:
            self.send_response(403);self.end_headers();return
        if self.path=='/status':
            data=json.dumps({'ok':True,'app':'AURA Download Manager','engine':'aria2','platform':'linux'}).encode()
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
        style=Gtk.CssProvider();style.load_from_path(str(ROOT/'style.css'))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),style,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.win=Gtk.Window(title='AURA Download Manager');self.win.set_default_size(1170,730);self.win.set_border_width(20)
        self.win.get_style_context().add_class('aura-manager')
        self.win.connect('delete-event',self.hide)
        outer=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16);self.win.add(outer)
        header=Gtk.Box(spacing=14);outer.pack_start(header,False,False,0)
        logo=Gtk.Image.new_from_icon_name('aura-download-manager',Gtk.IconSize.DIALOG) if Gtk.IconTheme.get_default().has_icon('aura-download-manager') else Gtk.Image.new_from_icon_name('folder-download',Gtk.IconSize.DIALOG);header.pack_start(logo,False,False,0)
        brand=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=2);header.pack_start(brand,True,True,0)
        heading=Gtk.Label(label='AURA Download Manager');heading.set_xalign(0);heading.get_style_context().add_class('aura-title');brand.pack_start(heading,False,False,0)
        subtitle=Gtk.Label(label='Fast downloads. Clean workflow. Powered by aria2.');subtitle.set_xalign(0);subtitle.get_style_context().add_class('aura-subtitle');brand.pack_start(subtitle,False,False,0)
        folder=Gtk.Button.new_from_icon_name('folder-open-symbolic',Gtk.IconSize.BUTTON);folder.set_tooltip_text('Open Downloads folder');folder.connect('clicked',lambda *_:subprocess.Popen(['xdg-open',str(DOWNLOADS)]));header.pack_end(folder,False,False,0)
        workspace=Gtk.Box(spacing=15);outer.pack_start(workspace,True,True,0)
        sidebar=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8)
        sidebar.get_style_context().add_class('aura-sidebar')
        sidebar.set_size_request(185,-1)
        workspace.pack_start(sidebar,False,False,0)
        main=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14)
        workspace.pack_start(main,True,True,0)
        self.view_filter='all'
        self.nav_buttons={}
        def nav(icon,caption,mode):
            button=Gtk.Button()
            content=Gtk.Box(spacing=12)
            content.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.BUTTON),False,False,0)
            label=Gtk.Label(label=caption);label.set_xalign(0)
            content.pack_start(label,True,True,0)
            button.add(content)
            button.get_style_context().add_class('aura-nav')
            button.connect('clicked',lambda *_:self.set_view(mode))
            sidebar.pack_start(button,False,False,0)
            self.nav_buttons[mode]=button
        nav('folder-download-symbolic','Downloads','all')
        nav('view-list-symbolic','Queue','waiting')
        nav('emblem-default-symbolic','Completed','complete')
        nav('emblem-system-symbolic','Settings','settings')
        self.set_view('all')
        self.main=main
        self.download_area=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=14);main.pack_start(self.download_area,True,True,0)
        stats=Gtk.Box(spacing=10);self.download_area.pack_start(stats,False,False,0)
        self.stat_labels={}
        for key,caption,icon in [('active','ACTIVE DOWNLOADS','emblem-synchronizing-symbolic'),('completed','COMPLETED','emblem-default-symbolic'),('speed','TOTAL SPEED','network-transmit-symbolic'),('queued','QUEUE','view-list-symbolic')]:
            card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=5);card.get_style_context().add_class('aura-card');stats.pack_start(card,True,True,0)
            top=Gtk.Box(spacing=8)
            top.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.BUTTON),False,False,0)
            title=Gtk.Label(label=caption);title.set_xalign(0);title.get_style_context().add_class('aura-stat-label');top.pack_start(title,False,False,0)
            card.pack_start(top,False,False,0)
            val=Gtk.Label(label='0');val.set_xalign(0);val.get_style_context().add_class('aura-stat-number');card.pack_start(val,False,False,0);self.stat_labels[key]=val
        toolbar=Gtk.Box(spacing=9);toolbar.get_style_context().add_class('aura-toolbar');self.download_area.pack_start(toolbar,False,False,0)
        self.entry=Gtk.Entry();self.entry.set_placeholder_text('Paste a direct download link (HTTP / HTTPS)…');self.entry.connect('activate',self.on_add);toolbar.pack_start(self.entry,True,True,0)
        b=Gtk.Button();add_row=Gtk.Box(spacing=7);add_row.pack_start(Gtk.Image.new_from_icon_name('list-add-symbolic',Gtk.IconSize.BUTTON),False,False,0);add_row.pack_start(Gtk.Label(label='Add download'),False,False,0);b.add(add_row);b.get_style_context().add_class('aura-primary');b.connect('clicked',self.on_add);toolbar.pack_start(b,False,False,0)
        actions=Gtk.FlowBox();actions.set_selection_mode(Gtk.SelectionMode.NONE);actions.set_row_spacing(7);actions.set_column_spacing(7);actions.set_max_children_per_line(7);self.download_area.pack_start(actions,False,False,0)
        controls=[('media-playback-pause-symbolic','Pause',lambda *_:self.action('pause')),('media-playback-start-symbolic','Resume',lambda *_:self.action('unpause')),('edit-select-all-symbolic','Select All',lambda *_:self.select_all_visible()),('edit-clear-symbolic','Remove Selected',lambda *_:self.bulk_remove()),('dialog-error-symbolic','Clear Failed',lambda *_:self.bulk_remove(failed_only=True)),('user-trash-symbolic','Delete',lambda *_:self.bulk_remove(delete_files=True)),('folder-open-symbolic','Open Folder',lambda *_:subprocess.Popen(['xdg-open',str(DOWNLOADS)]))]
        for icon,tip,callback in controls:
            b=Gtk.Button();inner=Gtk.Box(spacing=6);inner.pack_start(Gtk.Image.new_from_icon_name(icon,Gtk.IconSize.BUTTON),False,False,0);inner.pack_start(Gtk.Label(label=tip),False,False,0);b.add(inner);b.set_tooltip_text(tip);b.connect('clicked',callback);actions.add(b)
        list_card=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=6);list_card.get_style_context().add_class('aura-card');self.download_area.pack_start(list_card,True,True,0)
        self.listhead=Gtk.Label(label='DOWNLOADS');listhead=self.listhead;listhead.set_xalign(0);listhead.get_style_context().add_class('aura-stat-label');list_card.pack_start(listhead,False,False,0)
        self.store=Gtk.ListStore(str,str,str,str,str,str)
        self.filtered=self.store.filter_new();self.filtered.set_visible_func(self.is_visible);self.tree=Gtk.TreeView(model=self.filtered)
        for idx,title in enumerate(['File / URL','Status','Progress','Speed','Size','ID']):
            col=Gtk.TreeViewColumn(title,Gtk.CellRendererText(),text=idx);col.set_resizable(True);col.set_min_width(80);self.tree.append_column(col)
        self.tree.get_column(0).set_min_width(240)
        self.tree.get_column(5).set_visible(False)
        renderer=Gtk.CellRendererPixbuf()
        renderer.set_property('icon-name','user-trash-symbolic')
        col=Gtk.TreeViewColumn('DELETE',renderer)
        col.set_fixed_width(74)
        self.delete_column=col
        self.tree.append_column(col)
        self.tree.connect('button-press-event',self.on_row_click)
        self.tree.set_tooltip_text('Select rows for bulk actions, or click the trash icon on one row to delete its file.')
        self.tree.connect('key-press-event',self.on_list_key)
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.get_selection().connect('changed',self.selection_changed)
        scroll=Gtk.ScrolledWindow();scroll.add(self.tree);list_card.pack_start(scroll,True,True,0)
        self.settings_panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=18)
        self.settings_panel.get_style_context().add_class('aura-card')
        main.pack_start(self.settings_panel,True,True,0)
        self.settings_panel.set_no_show_all(False)
        title=Gtk.Label();title.set_markup('<span size="x-large" weight="bold">Download settings</span>');title.set_xalign(0);self.settings_panel.pack_start(title,False,False,0)
        caption=Gtk.Label(label='Configure aria2. Changes are applied immediately.');caption.set_xalign(0);self.settings_panel.pack_start(caption,False,False,0)
        settings_grid=Gtk.Grid(column_spacing=22,row_spacing=20);self.settings_panel.pack_start(settings_grid,False,False,0)
        self.setting_controls={}
        options=[('split','Connections per file (per server max 16)',1,16),('max-concurrent-downloads','Simultaneous downloads',1,20),('max-overall-download-limit','Total speed limit (KB/s, 0 = unlimited)',0,102400)]
        for row,(key,label,lower,upper) in enumerate(options):
            lab=Gtk.Label(label=label);lab.set_xalign(0);settings_grid.attach(lab,0,row,1,1)
            control=Gtk.SpinButton.new_with_range(lower,upper,1);control.set_numeric(True)
            self.setting_controls[key]=control;settings_grid.attach(control,1,row,1,1)
        apply=Gtk.Button(label='Apply settings');apply.get_style_context().add_class('aura-primary');apply.connect('clicked',self.apply_settings);self.settings_panel.pack_start(apply,False,False,0)
        pairing=Gtk.Box(spacing=12);self.settings_panel.pack_start(pairing,False,False,0)
        pair_label=Gtk.Label(label='Browser extension pairing');pair_label.set_xalign(0);pairing.pack_start(pair_label,True,True,0)
        pair_button=Gtk.Button.new_from_icon_name('edit-copy-symbolic',Gtk.IconSize.BUTTON);pair_button.set_tooltip_text('Copy one-time setup code for the browser extension');pair_button.connect('clicked',self.copy_pairing);pairing.pack_end(pair_button,False,False,0)
        notice=Gtk.Label(label='Files save to ~/Downloads. This panel controls the running aria2 engine.');notice.set_xalign(0);self.settings_panel.pack_start(notice,False,False,0)
        self.status=Gtk.Label(label='Ready');self.status.set_xalign(0);self.status.get_style_context().add_class('aura-footnote');outer.pack_start(self.status,False,False,0)
        self.ind=Indicator.Indicator.new('aura-download-manager','folder-download-symbolic',Indicator.IndicatorCategory.APPLICATION_STATUS)
        menu=Gtk.Menu()
        for title,cb in [('Show Download Manager',lambda *_:self.show()),('Open Downloads',lambda *_:subprocess.Popen(['xdg-open',str(DOWNLOADS)])),('Quit',lambda *_:self.quit())]:
            item=Gtk.MenuItem(label=title);item.connect('activate',cb);menu.append(item)
        menu.show_all();self.ind.set_menu(menu);self.ind.set_status(Indicator.IndicatorStatus.ACTIVE)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',PORT),Bridge);threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self._stopped_cache=[];self._stopped_at=0
        GLib.timeout_add(2500,self.refresh);self.refresh();self.win.show_all();self.settings_panel.hide()
    def set_view(self,mode):
        self.view_filter=mode
        for key,button in self.nav_buttons.items():
            ctx=button.get_style_context()
            if key==mode:ctx.add_class('aura-nav-active')
            else:ctx.remove_class('aura-nav-active')
        if hasattr(self,'settings_panel'):
            if mode=='settings':
                self.download_area.hide();self.settings_panel.show_all();self.settings_panel.set_visible(True);self.load_settings()
            else:
                self.settings_panel.hide();self.download_area.show_all()
                self.listhead.set_text({'all':'ALL DOWNLOADS','waiting':'QUEUED & PAUSED','complete':'COMPLETED DOWNLOADS'}[mode])
        if hasattr(self,'filtered'):self.filtered.refilter()
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
        return self.view_filter in ('all','settings') or (self.view_filter=='waiting' and model[itr][1] in ('waiting','paused')) or (self.view_filter=='complete' and model[itr][1]=='complete') or self.view_filter=='settings'
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
        if count:self.status.set_text(f'{count} selected • Pause, resume, remove history or delete files')

    def on_row_click(self,tree,event):
        if event.button!=1:return False
        hit=tree.get_path_at_pos(int(event.x),int(event.y))
        if not hit or hit[1]!=self.delete_column:return False
        path=hit[0]
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
        try:
            active=rpc('tellActive');waiting=rpc('tellWaiting',[0,1000])
            now=time.monotonic()
            if now-self._stopped_at>9:
                self._stopped_cache=rpc('tellStopped',[0,1000]);self._stopped_at=now
            entries=active+waiting+self._stopped_cache
            with YT_LOCK:yt_entries=[dict(x) for x in YOUTUBE_JOBS.values()]
            current={row[5]:row for row in self.store};seen=set()
            for e in entries:
                gid=e['gid'];seen.add(gid);total=int(e.get('totalLength') or 0);done=int(e.get('completedLength') or 0);speed=int(e.get('downloadSpeed') or 0)
                files=e.get('files',[]);name=pathlib.Path(files[0].get('path','')).name if files else ''
                if not name:name=(files[0].get('uris',[{}])[0].get('uri','') if files else gid)[:90]
                values=[name,e['status'],f'{done*100/total:.1f}%' if total else '0%',f'{speed/1024:.0f} KB/s',f'{done/1048576:.1f} / {total/1048576:.1f} MB',gid]
                if gid in current:
                    for j,val in enumerate(values):
                        if current[gid][j]!=val:current[gid][j]=val
                else:self.store.append(values)
            for y in yt_entries:
                gid=y['gid'];seen.add(gid)
                vals=[y['title']+' ('+y['quality']+')',y['status'],f"{y['percent']:.0f}%",'yt-dlp',y.get('error','')[:60],gid]
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
        except Exception as e:self.status.set_text('Download engine: '+str(e))
        return True

if __name__=='__main__':
    app=App();Gtk.main()
