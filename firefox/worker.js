'use strict';
const HOST='com.advertpreneur.aura';
const validUrl=url=>{
  try {const u=new URL(url);return ['http:','https:'].includes(u.protocol)&&!!u.hostname&&!u.username&&!u.password;}
  catch{return false;}
};
async function nativeRequest(command,payload={}) {
  try {
    const result=await browser.runtime.sendNativeMessage(HOST,{command,...payload});
    if (!result || result.ok===false) throw Error(result?.error || 'AURA desktop is unavailable.');
    return result;
  }catch(error){
    if (/native messaging host|specified native messaging host|host not found|permission to access/i.test(error.message))
      throw Error('AURA connection is not installed. Run the AURA desktop installer, then reload the extension.');
    throw error;
  }
}
async function add(url,kind=null) {
  if(!validUrl(url))throw Error('Use a valid HTTP or HTTPS URL.');
  return nativeRequest(kind?'stream':'add',{url,kind});
}
browser.runtime.onInstalled.addListener(()=>{
  browser.contextMenus.create({id:'aura-link',title:'Download with AURA',contexts:['link']});
  // Legacy browser tokens are revoked by the desktop upgrade.
});
browser.contextMenus.onClicked.addListener(info=>{
  if(info.menuItemId==='aura-link')add(info.linkUrl).catch(console.warn);
});
browser.runtime.onMessage.addListener(msg=>{
  if(!msg||!['aura.media.download','aura.download','aura.ping','aura.yt'].includes(msg.type))return;
  if(msg.type==='aura.ping')return nativeRequest('status').then(data=>({ok:true,...data})).catch(e=>({ok:false,error:e.message}));
  if(msg.type==='aura.yt'){
    if(!['add','formats'].includes(msg.path)||!validUrl(msg.payload?.url))return Promise.resolve({ok:false,error:'Invalid media request.'});
    return nativeRequest(msg.path==='add'?'yt_add':'formats',{url:msg.payload.url,quality:msg.payload.quality||'720'})
      .then(data=>({ok:true,...data})).catch(e=>({ok:false,error:e.message}));
  }
  return add(msg.url,msg.kind).then(data=>({ok:true,...data})).catch(e=>({ok:false,error:e.message}));
});
