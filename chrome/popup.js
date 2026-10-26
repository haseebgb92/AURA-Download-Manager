'use strict';
const api=globalThis.browser || globalThis.chrome;
const el=id=>document.getElementById(id);
const notice=(text,kind='')=>{el('notice').textContent=text;el('notice').className=kind;};
async function ping() {
  try {
    const r=await api.runtime.sendMessage({type:'aura.ping'});
    if(!r?.ok)throw Error(r?.error||'Desktop app unavailable.');
    el('state').textContent='Connected';el('state').classList.add('online');
    notice('Connected to desktop AURA.','success');
  }catch(e){
    el('state').textContent='Offline';el('state').classList.remove('online');notice(e.message,'error');
  }
}
(async()=>{
  const data=await api.storage.local.get('pairingToken');
  el('token').value=data.pairingToken||'';
  if(data.pairingToken)ping();
})();
el('toggle').addEventListener('click',()=>{
  const show=el('token').type==='password';el('token').type=show?'text':'password';el('toggle').textContent=show?'Hide':'Show';
});
el('pair').addEventListener('click',async()=>{
  const value=el('token').value.trim();
  if(value.length<24){notice('Enter the pairing code shown in AURA desktop Settings.','error');return;}
  await api.storage.local.set({pairingToken:value});await ping();
});
el('check').addEventListener('click',ping);
el('send').addEventListener('click',async()=>{
  const url=el('url').value.trim();
  try{
    const u=new URL(url);if(!['http:','https:'].includes(u.protocol))throw Error();
  }catch{notice('Paste a valid HTTP or HTTPS download URL.','error');return;}
  el('send').disabled=true;
  try{
    const res=await api.runtime.sendMessage({type:'aura.download',url});
    if(!res?.ok)throw Error(res?.error||'Unable to queue the download.');
    notice('Download added to AURA.','success');el('url').value='';
  }catch(e){notice(e.message,'error');}
  finally{el('send').disabled=false;}
});
