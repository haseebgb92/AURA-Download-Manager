'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function harness(browserName,options={}) {
  const handlers={},requests=[],browserOps=[],storage={autoCapture:options.autoCapture ?? true};
  const records=new Map();
  const api={
    runtime:{
      onInstalled:{addListener(fn){handlers.install=fn}},
      onStartup:{addListener(fn){handlers.startup=fn}},
      onMessage:{addListener(fn){handlers.message=fn}},
      async sendNativeMessage(host,message){
        requests.push({host,message});
        if (options.nativeThrows) throw Error('AURA offline');
        return options.nativeReply || {ok:true,gid:'test-download'};
      }
    },
    contextMenus:{
      create(info){handlers.menuOptions=info},
      onClicked:{addListener(fn){handlers.menu=fn}}
    },
    storage:{local:{
      async get(key) {return typeof key==='string'?{[key]:storage[key]}:{...storage};},
      async set(value){Object.assign(storage,value);},
      async remove(key){for(const k of [key].flat())delete storage[k];}
    }},
    downloads:{
      onCreated:{addListener(fn){handlers.created=fn}},
      async search({id}) {return records.has(id)?[records.get(id)]:[];},
      async pause(id) {
        browserOps.push(['pause',id]);
        if (options.pauseFails)throw Error('Already completed');
        const item=records.get(id);
        if(item)item.paused=true;
      },
      async resume(id){browserOps.push(['resume',id]);const item=records.get(id);if(item)item.paused=false;},
      async cancel(id){
        browserOps.push(['cancel',id]);
        if(options.cancelFails)throw Error('Could not cancel');
        const item=records.get(id);
        if(item)item.state='interrupted';
      },
      async erase({id}){browserOps.push(['erase',id]);return [id]}
    }
  };
  const context=vm.createContext({
    [browserName==='chrome'?'chrome':'browser']:api,
    URL, console, Promise, Date, Number, Array,
    setTimeout,clearTimeout,
    importScripts(file){vm.runInContext(fs.readFileSync(browserName+'/'+file,'utf8'),context)}
  });
  if(browserName==='firefox')
    vm.runInContext(fs.readFileSync(browserName+'/capture.js','utf8'),context);
  vm.runInContext(fs.readFileSync(browserName+'/worker.js','utf8'),context);
  async function dispatch(msg) {
    if(browserName==='chrome')
      return new Promise(resolve=>assert.equal(handlers.message(msg,{},resolve),true));
    return handlers.message(msg);
  }
  async function browserDownload(item) {
    records.set(item.id, {...item});
    await handlers.created(records.get(item.id));
  }
  return {handlers,requests,browserOps,storage,records,dispatch,browserDownload,api};
}

const file={id:12,url:'https://downloads.example.org/report.zip',mime:'application/zip',
  filename:'/home/test/Downloads/report.zip',danger:'safe',state:'in_progress',totalBytes:102400};
for(const name of ['chrome','firefox']){
  test(name+' auto-connects to the native host, not to a browser token',async()=>{
    const h=harness(name);
    const response=await h.dispatch({type:'aura.ping'});
    assert.equal(response.ok,true);
    assert.deepEqual(JSON.parse(JSON.stringify(h.requests)),[
      {host:'com.advertpreneur.aura',message:{command:'status'}}
    ]);
  });
  test(name+' auto-captures eligible files and cancels original only after accepted',async()=>{
    const h=harness(name);
    await h.browserDownload(file);
    assert.deepEqual(h.browserOps,[['pause',12],['cancel',12],['erase',12]]);
    assert.equal(h.requests.length,1);
    assert.equal(h.requests[0].message.command,'add');
    assert.equal(h.storage['auraPendingDownload:12'],undefined);
  });
  test(name+' excludes images by MIME and by extension, along with web assets',async()=>{
    const h=harness(name);
    for(const item of [
      {...file,id:13,url:'https://example.org/picture',filename:'image.bin',mime:'image/png'},
      {...file,id:14,url:'https://example.org/foo.jpg?size=large',filename:'picture.jpg',mime:'application/octet-stream'},
      {...file,id:15,url:'https://example.org/theme.woff2',filename:'font.woff2',mime:'application/octet-stream'},
      {...file,id:16,url:'https://example.org/index.html',filename:'index.html',mime:'text/html'}
    ])await h.browserDownload(item);
    assert.equal(h.browserOps.length,0);
    assert.equal(h.requests.length,0);
  });
  test(name+' keeps private, dangerous, and extension-initiated downloads in browser',async()=>{
    const h=harness(name);
    for(const item of [
      {...file,id:21,incognito:true},
      {...file,id:22,danger:'dangerous'},
      {...file,id:23,byExtensionId:'unrelated-extension'},
      {...file,id:24,url:'blob:https://example.org/98377'}
    ])await h.browserDownload(item);
    assert.equal(h.browserOps.length,0);
  });
  test(name+' honors user auto-capture switch',async()=>{
    const h=harness(name,{autoCapture:false});
    await h.browserDownload(file);
    assert.equal(h.browserOps.length,0);
    assert.equal(h.requests.length,0);
  });
  test(name+' resumes browser if AURA is unavailable',async()=>{
    const h=harness(name,{nativeThrows:true});
    await h.browserDownload(file);
    assert.deepEqual(h.browserOps,[['pause',12],['resume',12]]);
    assert.equal(h.records.get(12).paused,false);
    assert.equal(h.storage['auraPendingDownload:12'],undefined);
  });
  test(name+' leaves browser download alone when too fast to pause',async()=>{
    const h=harness(name,{pauseFails:true});
    await h.browserDownload(file);
    assert.deepEqual(h.browserOps,[['pause',12]]);
    assert.equal(h.requests.length,0);
  });
  test(name+' resumes browser when cancellation fails',async()=>{
    const h=harness(name,{cancelFails:true});
    await h.browserDownload(file);
    assert.deepEqual(h.browserOps,[['pause',12],['cancel',12],['resume',12]]);
  });
  test(name+' preserves explicit right-click for links and images',async()=>{
    const h=harness(name);
    assert.equal(h.handlers.install(),undefined);
    assert.deepEqual([...h.handlers.menuOptions.contexts],['link','image','video','audio']);
    await h.handlers.menu({menuItemId:'aura-link',srcUrl:'https://example.org/photo.png'});
    // Context menu handler is fire-and-forget, wait for native promise microtask.
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(h.requests[0].message.url,'https://example.org/photo.png');
  });
  test(name+' validates manual URL and stream requests',async()=>{
    const h=harness(name);
    assert.equal((await h.dispatch({type:'aura.download',url:'file:///etc/passwd'})).ok,false);
    const response=await h.dispatch({type:'aura.yt',path:'formats',payload:{url:'https://youtube.com/watch?v=abc'}});
    assert.equal(response.ok,true);
    assert.equal(h.requests[0].message.command,'formats');
  });
  test(name+' recovers a browser transfer paused during an interrupted handoff',async()=>{
    const h=harness(name);
    h.storage['auraPendingDownload:37']=Date.now();
    h.records.set(37,{...file,id:37,paused:true});
    await h.api.storage.local.get('auraPendingDownloads');
    // Recovery is attached to startup and uses browser downloads.search.
    h.handlers.startup();
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(h.browserOps,[['resume',37]]);
    assert.equal(h.storage['auraPendingDownload:37'],undefined);
  });
}
