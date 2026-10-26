'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

function harness(browserName,reply={ok:true,gid:'test-download'}) {
  const handlers={},requests=[],storeDeletes=[];
  const api={
    runtime:{
      onInstalled:{addListener(fn){handlers.install=fn}},
      onMessage:{addListener(fn){handlers.message=fn}},
      async sendNativeMessage(host,message){
        requests.push({host,message});
        return reply;
      }
    },
    contextMenus:{
      create(){},
      onClicked:{addListener(fn){handlers.menu=fn}}
    },
    storage:{local:{async remove(k){storeDeletes.push(k)}}}
  };
  vm.runInNewContext(fs.readFileSync(browserName+'/worker.js','utf8'),{
    [browserName==='chrome'?'chrome':'browser']:api,URL,console,Promise
  });
  async function dispatch(msg) {
    if(browserName==='chrome'){
      return new Promise(resolve=>{
        assert.equal(handlers.message(msg,{},resolve),true);
      });
    }
    return await handlers.message(msg);
  }
  return {handlers,requests,storeDeletes,dispatch};
}
for(const name of ['chrome','firefox']){
  test(name+' automatically uses authorized native messaging, never token',async()=>{
    const h=harness(name);
    const response=await h.dispatch({type:'aura.ping'});
    assert.equal(response.ok,true);
    assert.deepEqual(JSON.parse(JSON.stringify(h.requests)),[
      {host:'com.advertpreneur.aura',message:{command:'status'}}
    ]);
    assert.equal(h.requests[0].message.pairingToken,undefined);
  });
  test(name+' preserves explicit-only download handoff',async()=>{
    const h=harness(name);
    const res=await h.dispatch({type:'aura.download',url:'https://example.org/sample.zip'});
    assert.equal(res.ok,true);
    assert.equal(h.requests.length,1);
    assert.equal(h.requests[0].message.command,'add');
    assert.equal(h.requests[0].message.url,'https://example.org/sample.zip');
    assert.equal(h.requests[0].message.intent,undefined);
    assert.equal(h.handlers.downloads,undefined);
  });
  test(name+' rejects invalid schemes and embedded credentials',async()=>{
    const h=harness(name);
    for(const url of ['file:///etc/passwd','javascript:alert(1)','https://user:secret@example.com/z']){
      const r=await h.dispatch({type:'aura.download',url});
      assert.equal(r.ok,false);
    }
    assert.equal(h.requests.length,0);
  });
  test(name+' reports desktop-offline state',async()=>{
    const h=harness(name,{ok:false,error:'AURA is offline.'});
    const r=await h.dispatch({type:'aura.ping'});
    assert.equal(r.ok,false);
    assert.match(r.error,/offline/i);
  });
  test(name+' retains stream and yt routing',async()=>{
    const h=harness(name);
    await h.dispatch({type:'aura.media.download',url:'https://example.org/live.m3u8',kind:'hls'});
    await h.dispatch({type:'aura.yt',path:'formats',payload:{url:'https://youtube.com/watch?v=a'}});
    assert.equal(h.requests[0].message.command,'stream');
    assert.equal(h.requests[1].message.command,'formats');
  });
}
