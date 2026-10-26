(()=>{
  if(globalThis.__auraMediaLoaded)return;
  globalThis.__auraMediaLoaded=true;
  let current=null,kind=null;
  const candidates=new Map();
  const streamType=url=>/\.m3u8(?:[?#]|$)/i.test(url)?'hls':/\.mpd(?:[?#]|$)/i.test(url)?'dash':null;
  function discover(url){try{const u=new URL(url,location.href);const type=streamType(u.href);if(!type||!/^https?:$/.test(u.protocol))return;candidates.set(u.href,type);if(candidates.size>30)candidates.delete(candidates.keys().next().value);}catch{}}
  function discoverPerformance(){for(const entry of performance.getEntriesByType('resource'))discover(entry.name);}
  discoverPerformance();
  new PerformanceObserver(discoverPerformance).observe({entryTypes:['resource']});
  const supported=url=>{try{const u=new URL(url,location.href);return /^https?:$/.test(u.protocol)&&(/\.(mp4|m4v|webm|mp3|m4a|aac|ogg|opus|wav|flac)([?#]|$)/i.test(u.href));}catch{return false;}};
  const sourceFor=el=>[el.currentSrc,el.src,...Array.from(el.querySelectorAll('source')).map(s=>s.src)].find(s=>s&&supported(s));
  const wrap=document.createElement('div');wrap.id='aura-media-helper';
  Object.assign(wrap.style,{position:'fixed',right:'16px',top:'16px',zIndex:'2147483646',display:'none',font:'600 13px system-ui,sans-serif',color:'#fff',background:'#246be0',padding:'0',borderRadius:'12px',boxShadow:'0 6px 24px #0004',overflow:'hidden'});
  const btn=document.createElement('button');btn.type='button';btn.textContent='↓ Download media';
  Object.assign(btn.style,{padding:'10px 16px',cursor:'pointer',border:0,color:'white',background:'transparent',font:'inherit'});
  btn.onclick=async()=>{
    if(!current)return;
    btn.disabled=true;btn.textContent='Sending to AURA…';
    try{const res=await (globalThis.chrome||globalThis.browser).runtime.sendMessage({type:'aura.media.download',url:current,kind});if(!res?.ok)throw Error(res?.error||'Request failed');btn.textContent='✓ Added to AURA';}
    catch(e){btn.textContent='! '+String(e.message).slice(0,36);}
    setTimeout(()=>{btn.textContent=kind?'↓ Download '+kind.toUpperCase():'↓ Download media';btn.disabled=false;},2200);
  };
  wrap.append(btn);
  (document.body||document.documentElement).append(wrap);
  function scan(){
    const elems=[...document.querySelectorAll('video,audio')];
    let pick=null;
    for(const el of elems){const rect=el.getBoundingClientRect();if(rect.width>80&&rect.height>30&&rect.bottom>0&&rect.top<innerHeight){const src=sourceFor(el);if(src){pick={el,src};break;}}}
    if(!pick && !candidates.size){wrap.style.display='none';current=null;return;}
    if(pick){current=pick.src;kind=null;}
    else{const selected=[...candidates.entries()].at(-1);current=selected[0];kind=selected[1];}
    btn.textContent=kind?'↓ Download '+kind.toUpperCase():'↓ Download media';
    const r=pick?pick.el.getBoundingClientRect():{top:16,right:innerWidth-16};
    wrap.style.top=Math.max(10,Math.min(innerHeight-45,r.top+12))+'px';
    wrap.style.right=Math.max(10,innerWidth-r.right+12)+'px';
    wrap.style.display='block';
  }
  document.addEventListener('play',scan,true);
  document.addEventListener('loadedmetadata',scan,true);
  let scanTimer=null;
  function scheduleScan(){
    if(scanTimer!==null)return;
    scanTimer=setTimeout(()=>{scanTimer=null;scan();},180);
  }
  document.addEventListener('scroll',scheduleScan,{passive:true});
  new MutationObserver(scheduleScan).observe(document.documentElement,{subtree:true,childList:true});
  // YouTube uses client-side navigation; maintain one panel as videos change.
  let ytPanel=null;
  function syncYouTubePanel(){
    const watch=/(^|\.)youtube\.com$/.test(location.hostname)&&location.pathname==='/watch'&&new URLSearchParams(location.search).has('v');
    if(!watch){if(ytPanel){ytPanel.remove();ytPanel=null;}return;}
    if(ytPanel&&ytPanel.isConnected)return;
    ytPanel=document.createElement('div');
    ytPanel.id='aura-youtube-panel';
    ytPanel.style.cssText='position:fixed;right:22px;bottom:24px;z-index:2147483647;background:#fff;color:#1f3556;border:1px solid #cde1ff;border-radius:12px;padding:12px;box-shadow:0 8px 28px #0004;font:13px system-ui,sans-serif;';
    ytPanel.innerHTML='<strong>AURA YouTube</strong><div style="margin:9px 0"><select aria-label="Quality"><option value="1080">1080p</option><option value="720" selected>720p</option><option value="480">480p</option><option value="360">360p</option><option value="audio">Audio only</option></select></div><button style="background:#246be0;color:white;padding:8px 12px;border:0;border-radius:8px;cursor:pointer">↓ Download with AURA</button><div class="aura-note" style="max-width:240px;margin-top:6px"></div>';
    (document.body||document.documentElement).append(ytPanel);
    ytPanel.querySelector('button').onclick=async()=>{
      const note=ytPanel.querySelector('.aura-note');note.textContent='Sending…';
      try{const res=await (globalThis.chrome||globalThis.browser).runtime.sendMessage({type:'aura.yt',path:'add',payload:{url:location.href,quality:ytPanel.querySelector('select').value}});if(!res?.ok)throw Error(res?.error||'Request failed');note.textContent='Added to AURA';}
      catch(e){note.textContent='Error: '+String(e.message).slice(0,100);}
    };
  }
  window.addEventListener('yt-navigate-finish',syncYouTubePanel);
  window.addEventListener('popstate',syncYouTubePanel);
  syncYouTubePanel();
  setInterval(syncYouTubePanel,1800);
  scan();
  setInterval(scan,4000);
})();
