'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function chromeHarness(token = 'valid-pairing-token') {
  const handlers = {};
  let reads = [];
  const chrome = {
    runtime: {
      onInstalled: {addListener(fn){handlers.installed=fn}},
      onMessage: {addListener(fn){handlers.message=fn}},
    },
    contextMenus:{
      create() {},
      onClicked:{addListener(fn){handlers.menu=fn}}
    },
    storage:{local:{
      async get(){return {pairingToken:token}},
      async remove(key){assert.equal(key,'autoCapture')}
    }}
  };
  const context = {chrome,URL,Promise,console,fetch:async (url,options)=>{
    reads.push({url,options});
    return {ok:true,async json(){return {ok:true,gid:'test-gid'}}};
  }};
  vm.runInNewContext(fs.readFileSync('chrome/worker.js','utf8'),context);
  return {handlers,reads,chrome};
}

test('Chrome extension only captures explicit user actions', async()=>{
  const h=chromeHarness();
  assert.equal(h.chrome.downloads,undefined);
  assert.equal(typeof h.handlers.installed,'function');
  await h.handlers.installed();
  const data=await new Promise(resolve=>{
    const staysOpen=h.handlers.message({type:'aura.download',url:'https://example.com/file.zip'},null,resolve);
    assert.equal(staysOpen,true);
  });
  assert.equal(data.ok,true);
  assert.equal(h.reads.length,1);
  assert.equal(h.reads[0].url,'http://127.0.0.1:18763/add');
  assert.equal(JSON.parse(h.reads[0].options.body).intent,'user');
});

test('rejects invalid URLs without sending requests', async()=>{
  const h=chromeHarness();
  const response=await new Promise(resolve=>h.handlers.message({type:'aura.download',url:'file:///etc/passwd'},null,resolve));
  assert.equal(response.ok,false);
  assert.equal(h.reads.length,0);
});

test('does not connect without a pairing code',async()=>{
  const h=chromeHarness('');
  const response=await new Promise(resolve=>h.handlers.message({type:'aura.ping'},null,resolve));
  assert.equal(response.ok,false);
  assert.match(response.error,/Pair AURA/);
  assert.equal(h.reads.length,0);
});

test('status requests use GET and a paired token',async()=>{
  const h=chromeHarness();
  const response=await new Promise(resolve=>h.handlers.message({type:'aura.ping'},null,resolve));
  assert.equal(response.ok,true);
  assert.equal(h.reads[0].url,'http://127.0.0.1:18763/status');
  assert.equal(h.reads[0].options.headers['X-Aura-Token'],'valid-pairing-token');
  assert.equal(h.reads[0].options.method,'GET');
});
