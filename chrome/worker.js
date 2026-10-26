'use strict';
const API = 'http://127.0.0.1:18763';
const validUrl = url => {
  try { const u = new URL(url); return ['http:', 'https:'].includes(u.protocol); }
  catch { return false; }
};
async function request(path, payload) {
  const { pairingToken } = await chrome.storage.local.get('pairingToken');
  if (!pairingToken) throw Error('Pair AURA in the extension popup first.');
  const response = await fetch(API + path, {
    method: payload ? 'POST' : 'GET',
    headers: { 'X-Aura-Token': pairingToken, ...(payload ? { 'Content-Type':'application/json' } : {}) },
    ...(payload ? { body: JSON.stringify(payload) } : {})
  });
  let data;
  try { data = await response.json(); }
  catch { throw Error('Desktop AURA is not responding. Start the app first.'); }
  if (!response.ok || data.ok === false) throw Error(data.error || 'AURA request failed.');
  return data;
}
async function add(url, kind) {
  if (!validUrl(url)) throw Error('Use a valid HTTP or HTTPS URL.');
  return request(kind ? '/stream' : '/add', { url, kind, intent:'user' });
}
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id:'aura-link', title:'Download with AURA', contexts:['link'] });
  chrome.storage.local.remove('autoCapture'); // retire legacy interception preference
});
chrome.contextMenus.onClicked.addListener(info => {
  if (info.menuItemId === 'aura-link') add(info.linkUrl).catch(console.warn);
});
// The browser owns ordinary downloads. No downloads.onCreated listener.
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (!msg || !['aura.media.download','aura.download','aura.ping','aura.yt'].includes(msg.type)) return false;
  let task;
  if (msg.type === 'aura.ping') task = request('/status');
  else if (msg.type === 'aura.yt') {
    if (!['add','formats'].includes(msg.path) || !validUrl(msg.payload?.url)) task = Promise.reject(Error('Invalid media request.'));
    else task = request('/yt/' + msg.path, msg.payload);
  } else task = add(msg.url, msg.kind || null);
  task.then(data => reply({ok:true,...data})).catch(e=>reply({ok:false,error:e.message}));
  return true;
});
