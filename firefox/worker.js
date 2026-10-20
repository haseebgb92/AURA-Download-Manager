const token = 'XuRWMwiTVP3I2k_vgZeDR3VKPEEVz35iCizZv2P06Z8';
async function downloadWithAura(url,kind) {
 const res = await fetch('http://127.0.0.1:18763/'+(kind?'stream':'add'), {method:'POST',headers:{'Content-Type':'application/json','X-Aura-Token':token},body:JSON.stringify({url,kind})});
 const data = await res.json();
 if (!data.ok) throw new Error(data.error || 'Could not send download');
}
browser.runtime.onInstalled.addListener(() => browser.contextMenus.create({id:'aura',title:'Download with AURA',contexts:['link']}));
browser.contextMenus.onClicked.addListener(async info => {
 if(info.menuItemId !== 'aura') return;
 try {await downloadWithAura(info.linkUrl);}catch(error){console.error('AURA: '+error.message);}
});

// Requests from the media overlay.
browser.runtime.onMessage.addListener((msg)=>{
 if(msg?.type!=='aura.media.download')return;
 return downloadWithAura(msg.url,msg.kind).then(()=>({ok:true})).catch(e=>({ok:false,error:e.message}));
});

async function auraYt(path,payload){const res=await fetch('http://127.0.0.1:18763/yt/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-Aura-Token':token},body:JSON.stringify(payload)});const data=await res.json();if(!data.ok)throw Error(data.error||'YouTube request failed');return data;}
browser.runtime.onMessage.addListener(msg=>{if(msg?.type==='aura.yt')return auraYt(msg.path,msg.payload).catch(e=>({ok:false,error:e.message}));});
