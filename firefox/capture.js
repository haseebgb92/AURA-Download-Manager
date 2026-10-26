'use strict';
/* Shared Chrome + Firefox auto handoff. No browser cookies, passwords or files
   are copied; only download URLs are submitted through AURA Native Messaging. */
globalThis.AuraCapture = (() => {
  const IMAGE_EXT = /\.(?:png|jpe?g|gif|webp|avif|bmp|tiff?|ico|svg|heic|heif|apng|jfif|jxl)(?:$|[?#])/i;
  const WEB_ASSET_EXT = /\.(?:css|m?js|woff2?|ttf|otf|eot|map)(?:$|[?#])/i;
  const SKIP_MIME = /^(?:image\/|font\/|text\/html(?:;|$)|text\/css(?:;|$)|text\/javascript(?:;|$)|application\/(?:javascript|x-javascript|font-woff)(?:;|$))/i;
  const inFlight = new Set();
  const AUTO_KEY = 'autoCapture';
  const PENDING_PREFIX = 'auraPendingDownload:';
  const timeoutMs = 10000;

  function validUrl(url) {
    try {
      const parsed = new URL(url);
      return (parsed.protocol === 'https:' || parsed.protocol === 'http:') &&
        !!parsed.hostname && !parsed.username && !parsed.password;
    } catch { return false; }
  }
  function eligible(item, extensionId) {
    if (!item || !Number.isInteger(item.id) || item.incognito ||
        (item.state && item.state !== 'in_progress') ||
        item.byExtensionId || item.byExtensionName ||
        (item.danger && !['safe','accepted'].includes(item.danger))) return false;
    const url = item.finalUrl || item.url || '';
    if (!validUrl(url)) return false;
    const filename = (item.filename || '').replace(/\\/g, '/');
    if (SKIP_MIME.test(item.mime || '')) return false;
    if (IMAGE_EXT.test(filename) || IMAGE_EXT.test(url)) return false;
    if (WEB_ASSET_EXT.test(filename) || WEB_ASSET_EXT.test(url)) return false;
    // Do not hijack tiny web resources. Files with a recognizable download
    // filename (e.g. "report.pdf") are still eligible regardless of size.
    if ((item.totalBytes >= 0 && item.totalBytes < 32768) &&
        !/\.(?:zip|7z|rar|pdf|docx?|xlsx?|pptx?|exe|msi|dmg|deb|rpm|apk|mp4|mp3|csv|json|txt)(?:$|[?#])/i.test(filename || url))
      return false;
    return true;
  }
  // One key per paused browser item avoids a race when multiple downloads
  // arrive at the same time (merging one shared JSON object could lose entries).
  async function recover(api) {
    const all = await api.storage.local.get(null);
    for (const [key] of Object.entries(all)) {
      if (!key.startsWith(PENDING_PREFIX)) continue;
      const id=Number(key.slice(PENDING_PREFIX.length));
      if (Number.isInteger(id) && id>=0) {
        try {
          const results=await api.downloads.search({id});
          if (results?.[0]?.paused) await api.downloads.resume(id);
        } catch { /* browser may have removed the file */ }
      }
      try { await api.storage.local.remove(key); } catch { /* retry on next startup */ }
    }
  }
  function register(api, nativeRequest, logger=console) {
    async function process(item) {
      if (!item || inFlight.has(item.id)) return;
      inFlight.add(item.id);
      let paused = false, stored = false;
      try {
        const opts = await api.storage.local.get(AUTO_KEY);
        if (opts[AUTO_KEY] === false) return;
        const latest = (await api.downloads.search({id:item.id}))[0] || item;
        if (!eligible({...item,...latest})) return;
        // Pause before starting AURA to prevent duplicate local downloads.
        // If this fails (e.g., a tiny already-completed file), keep it in browser.
        try { await api.downloads.pause(item.id); paused = true; }
        catch { return; }
        await api.storage.local.set({[PENDING_PREFIX+item.id]:Date.now()});
        stored = true;
        const url = latest.finalUrl || latest.url || item.finalUrl || item.url;
        // Desktop acknowledges queuing; AURA downloads without the browser's
        // credentials. Sites needing browser sessions may fail in aria2.
        let timer;
        let queued;
        try {
          queued=await Promise.race([
            nativeRequest('add',{url}),
            new Promise((_,reject)=>{
              timer=setTimeout(()=>reject(Error('AURA connection timed out')),timeoutMs);
            })
          ]);
        } finally {
          clearTimeout(timer);
        }
        if (!queued?.ok || !queued.gid) throw Error('AURA did not confirm a queued download.');
        try {
          await api.downloads.cancel(item.id);
          paused = false;
          // Clean up only the abandoned browser-history entry after cancellation.
          try { await api.downloads.erase({id:item.id}); } catch { /* optional cleanup */ }
        } catch (error) {
          logger.warn('AURA accepted a download but browser cancellation failed:',error.message);
          // Never leave the user's browser transfer paused.
        }
      } catch(error) {
        logger.warn('AURA automatic handoff left this download in the browser:',error.message);
      } finally {
        if (paused) {
          try { await api.downloads.resume(item.id); } catch { /* interrupted */ }
        }
        if (stored) {
          try {
            await api.storage.local.remove(PENDING_PREFIX+item.id);
          } catch { /* startup recovery will retry if retained */ }
        }
        inFlight.delete(item.id);
      }
    }
    api.downloads.onCreated.addListener(item=>
      // Event listener remains registered at worker startup (MV3 compatible).
      process(item).catch(error=>logger.warn('AURA auto-capture failed:',error.message))
    );
    return {process,recover:()=>recover(api)};
  }
  return {eligible,register,recover,validUrl};
})();
