'use strict';
const api=globalThis.browser || globalThis.chrome;
const el=id=>document.getElementById(id);
const notice=(text,kind='')=>{el('notice').textContent=text;el('notice').className=kind;};
async function ping(){
  try{
    const response=await api.runtime.sendMessage({type:'aura.ping'});
    if(!response?.ok)throw Error(response?.error||'AURA desktop is unavailable.');
    el('state').textContent='Connected';
    el('state').classList.add('online');
    notice('Connected automatically to AURA desktop.','success');
  }catch(error){
    el('state').textContent='Offline';
    el('state').classList.remove('online');
    notice(error.message||'Open AURA on your computer.','error');
  }
}
el('check').addEventListener('click',ping);
el('send').addEventListener('click',async()=>{
  const url=el('url').value.trim();
  try {
    const u=new URL(url);
    if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password)throw Error();
  }catch {notice('Paste a valid HTTP or HTTPS download URL.','error');return;}
  el('send').disabled=true;
  try{
    const r=await api.runtime.sendMessage({type:'aura.download',url});
    if(!r?.ok)throw Error(r?.error||'Could not queue the download.');
    notice('Download added to AURA.','success');el('url').value='';
  }catch(error){notice(error.message,'error');}
  finally{el('send').disabled=false;}
});
ping();
