'use strict';
const API = 'http://127.0.0.1:18763';
const validUrl = url => {
  try { return ['http:','https:'].includes(new URL(url).protocol); }
  catch { return false; }
};
async function request(path,payload) {
  const {pairingToken} = await browser.storage.local.get('pairingToken');
  if (!pairingToken) throw Error('Pair AURA in the extension popup first.');
  const response = await fetch(API+path, {
    method:payload?'POST':'GET',
    headers:{'X-Aura-Token':pairingToken,...(payload?{'Content-Type':'application/json'}:{})},
    ...(payload?{body:JSON.stringify(payload)}:{})
  });
  let data;
  try {data=await response.json();}
  catch{throw Error('Desktop AURA is not responding. Start the app first.');}
  if(!response.ok||data.ok===false)throw Error(data.error||'AURA request failed.');
  return data;
}
async function add(url,kind) {
  if(!validUrl(url))throw Error('Use a valid HTTP or HTTPS URL.');
  return request(kind?'/stream':'/add',{url,kind,intent:'user'});
}
browser.runtime.onInstalled.addListener(()=>browser.contextMenus.create({id:'aura-link',title:'Download with AURA',contexts:['link']}));
browser.contextMenus.onClicked.addListener(info=>{
  if(info.menuItemId==='aura-link')add(info.linkUrl).catch(console.warn);
});
browser.runtime.onMessage.addListener(msg=>{
  if(!msg||!['aura.media.download','aura.download','aura.ping','aura.yt'].includes(msg.type))return;
  if(msg.type==='aura.ping')return request('/status').then(data=>({ok:true,...data})).catch(e=>({ok:false,error:e.message}));
  if(msg.type==='aura.yt') {
    if(!['add','formats'].includes(msg.path)||!validUrl(msg.payload?.url))return Promise.resolve({ok:false,error:'Invalid media request.'});
    return request('/yt/'+msg.path,msg.payload).then(data=>({ok:true,...data})).catch(e=>({ok:false,error:e.message}));
  }
  return add(msg.url,msg.kind).then(data=>({ok:true,...data})).catch(e=>({ok:false,error:e.message}));
});
