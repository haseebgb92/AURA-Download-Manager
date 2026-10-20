const token = 'XuRWMwiTVP3I2k_vgZeDR3VKPEEVz35iCizZv2P06Z8';
async function downloadWithAura(url,kind) {
 const res = await fetch('http://127.0.0.1:18763/'+(kind?'stream':'add'), {method:'POST',headers:{'Content-Type':'application/json','X-Aura-Token':token},body:JSON.stringify({url,kind})});
 const data = await res.json();
 if (!data.ok) throw new Error(data.error || 'Could not send download');
}
chrome.runtime.onInstalled.addListener(() => chrome.contextMenus.create({id:'aura',title:'Download with AURA',contexts:['link']}));
chrome.contextMenus.onClicked.addListener(async info => {
 if(info.menuItemId !== 'aura') return;
 try {await downloadWithAura(info.linkUrl);}catch(error){console.error('AURA: '+error.message);}
});

// Optional automatic capture, disabled by default to avoid disrupting normal browser downloads.
chrome.downloads.onCreated.addListener(async item => {
 const settings=await chrome.storage.local.get('autoCapture');
 if(!settings.autoCapture || !(item.finalUrl||item.url||'').match(/^https?:/i) || item.byExtensionId)return;
 try {
   await downloadWithAura(item.finalUrl||item.url);
   await chrome.downloads.cancel(item.id);
   await chrome.downloads.erase({id:item.id});
 } catch(err){console.warn('AURA kept Chrome download:',err.message);}
});
chrome.action.onClicked.addListener(async ()=>{
 const s=await chrome.storage.local.get('autoCapture');
 const next=!s.autoCapture;await chrome.storage.local.set({autoCapture:next});
 await chrome.action.setBadgeText({text:next?'ON':'OFF'});
 await chrome.action.setBadgeBackgroundColor({color:next?'#2968d9':'#64748b'});
});

// Requests from the media overlay; the local bridge validates every request.
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{
 if(msg?.type!=='aura.media.download')return false;
 downloadWithAura(msg.url,msg.kind).then(()=>reply({ok:true})).catch(e=>reply({ok:false,error:e.message}));
 return true;
});

async function auraYt(path,payload){const res=await fetch('http://127.0.0.1:18763/yt/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Aura-Token':token},body:JSON.stringify(payload)});const data=await res.json();if(!data.ok)throw Error(data.error||'YouTube request failed');return data;}
chrome.runtime.onMessage.addListener((msg,sender,reply)=>{if(msg?.type!=='aura.yt')return false;auraYt(msg.path,msg.payload).then(reply).catch(e=>reply({ok:false,error:e.message}));return true;});
