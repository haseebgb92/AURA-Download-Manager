'use strict';
const HOST = 'com.advertpreneur.aura';
const validUrl = url => {
  try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol) && !!u.hostname && !u.username && !u.password; }
  catch { return false; }
};
async function nativeRequest(command, payload={}) {
  try {
    const result = await chrome.runtime.sendNativeMessage(HOST, {command, ...payload});
    if (!result || result.ok === false) throw Error(result?.error || 'AURA desktop is unavailable.');
    return result;
  } catch(error) {
    if (/native messaging host|specified native messaging host|host not found|permission to access/i.test(error.message))
      throw Error('AURA connection is not installed. Run the AURA desktop installer, then reload the extension.');
    throw error;
  }
}
async function add(url,kind=null) {
  if (!validUrl(url)) throw Error('Use a valid HTTP or HTTPS URL.');
  return nativeRequest(kind ? 'stream' : 'add', {url,kind});
}
chrome.runtime.onInstalled.addListener(()=>{
  chrome.contextMenus.create({id:'aura-link',title:'Download with AURA',contexts:['link']});
  // Legacy browser tokens are revoked by the desktop upgrade.
});
chrome.contextMenus.onClicked.addListener(info => {
  if (info.menuItemId === 'aura-link') add(info.linkUrl).catch(console.warn);
});
// Ordinary Chrome downloads stay in Chrome; no downloads.onCreated event.
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
  if (!msg || !['aura.media.download','aura.download','aura.ping','aura.yt'].includes(msg.type)) return false;
  let task;
  if (msg.type==='aura.ping') task=nativeRequest('status');
  else if (msg.type==='aura.yt') {
    if (!['add','formats'].includes(msg.path) || !validUrl(msg.payload?.url))
      task=Promise.reject(Error('Invalid media request.'));
    else task=nativeRequest(msg.path==='add'?'yt_add':'formats',
      {url:msg.payload.url,quality:msg.payload.quality || '720'});
  } else task=add(msg.url,msg.kind || null);
  task.then(data=>reply({ok:true,...data})).catch(e=>reply({ok:false,error:e.message}));
  return true;
});
