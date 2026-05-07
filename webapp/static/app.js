const $ = (id) => document.getElementById(id);

async function search(q){
  if(!q) return [];
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  if(!res.ok) return [];
  return await res.json();
}

function renderSuggestions(container, items){
  container.innerHTML = '';
  if(!items || items.length === 0){
    // show explicit no-matches message when user typed something
    const input = container.previousElementSibling;
    if (input && input.value && input.value.trim() !== ''){
      const no = document.createElement('div');
      no.className = 'suggest';
      no.style.opacity = '0.7';
      no.textContent = 'No matches';
      container.appendChild(no);
    }
    return;
  }
  items.slice(0,5).forEach(it => {
    const div = document.createElement('div');
    div.className = 'suggest';
    div.textContent = `${it.name} (${it.id64})`;
    div.addEventListener('click', ()=>{
      const input = container.previousElementSibling;
      input.value = it.name;
      container.innerHTML = '';
    });
    container.appendChild(div);
  });
}

let srcTimer = null, tgtTimer = null;
$('source').addEventListener('input', (e)=>{
  clearTimeout(srcTimer);
  const v = e.target.value;
  srcTimer = setTimeout(async ()=>{
    const items = await search(v);
    renderSuggestions($('src-suggestions'), items);
  }, 200);
});
$('target').addEventListener('input', (e)=>{
  clearTimeout(tgtTimer);
  const v = e.target.value;
  tgtTimer = setTimeout(async ()=>{
    const items = await search(v);
    renderSuggestions($('tgt-suggestions'), items);
  }, 200);
});

$('reverse').addEventListener('click', ()=>{
  const s = $('source').value;
  $('source').value = $('target').value;
  $('target').value = s;
});

let es = null;
$('find').addEventListener('click', async ()=>{
  const source = $('source').value.trim();
  const target = $('target').value.trim();
  const max_hop = parseFloat($('max-hop').value) || 400;
  // basic validation
  if(!source || !target){
    $('info').textContent = 'Enter both source and target';
    return;
  }
  // quick pre-check: ensure source/target resolve to at least one system
  try{
    const [sres, tres] = await Promise.all([search(source), search(target)]);
    if(!sres || sres.length === 0){
      $('info').textContent = `Source not found: ${source}`;
      return;
    }
    if(!tres || tres.length === 0){
      $('info').textContent = `Target not found: ${target}`;
      return;
    }
  }catch(e){
    // ignore and proceed to let server return proper error
  }

  $('info').textContent = 'Searching...';
  $('path-list').innerHTML = '';
  // close previous EventSource if any
  if(es){
    es.close();
    es = null;
  }
  const params = new URLSearchParams({source, target, max_hop});
  es = new EventSource(`/api/path/stream?${params.toString()}`);
  es.addEventListener('progress', (ev)=>{
    try{
      const txt = ev.data;
      console.log(txt);
      $('info').textContent = txt;
    }catch(e){/*ignore*/}
  });
  es.addEventListener('result', (ev)=>{
    try{
      const data = JSON.parse(ev.data);
      console.log('Result:', data);
      if(data.error){
        $('info').textContent = data.error;
      }else{
        $('info').textContent = `Total: ${data.total.toFixed(1)}ly | Direct: ${data.direct.toFixed(1)}ly | Diff: +${data.diff_pct.toFixed(1)}%`;
        const list = $('path-list');
        data.path.forEach((p, i)=>{
          const li = document.createElement('li');
          // Build DOM nodes safely to avoid XSS — do not use innerHTML with untrusted data
          const strong = document.createElement('strong');
          strong.textContent = `${i+1}) ${p.name}`;
          li.appendChild(strong);
          const meta = document.createTextNode(` id=${p.id64} coords=(${p.coords.x.toFixed(1)}, ${p.coords.y.toFixed(1)}, ${p.coords.z.toFixed(1)}) hop=${p.hop_dist.toFixed(1)} mainStar=${p.mainStar || ''}`);
          li.appendChild(meta);
          // click to copy system name to clipboard
          li.style.cursor = 'pointer';
          li.title = 'Click to copy system name';
          li.addEventListener('click', async ()=>{
            const txt = p.name || '';
            try{
              if(navigator.clipboard && navigator.clipboard.writeText){
                await navigator.clipboard.writeText(txt);
              }else{
                // fallback
                const ta = document.createElement('textarea');
                ta.value = txt;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
              }
              // Manage info area restore so multiple quick clicks don't overwrite previous content incorrectly
              if (window._infoRestoreTimeout == null) {
                window._infoPrevText = $('info').textContent;
              }
              $('info').textContent = `Copied: ${txt}`;
              if (window._infoRestoreTimeout) {
                clearTimeout(window._infoRestoreTimeout);
              }
              window._infoRestoreTimeout = setTimeout(()=>{
                $('info').textContent = window._infoPrevText || '';
                window._infoRestoreTimeout = null;
                window._infoPrevText = null;
              }, 2000);
            }catch(e){
              if (window._infoRestoreTimeout == null) {
                window._infoPrevText = $('info').textContent;
              }
              $('info').textContent = `Copy failed`;
              if (window._infoRestoreTimeout) {
                clearTimeout(window._infoRestoreTimeout);
              }
              window._infoRestoreTimeout = setTimeout(()=>{
                $('info').textContent = window._infoPrevText || '';
                window._infoRestoreTimeout = null;
                window._infoPrevText = null;
              }, 2000);
            }
          });
          list.appendChild(li);
        });
      }
    }catch(e){
      $('info').textContent = 'Error parsing result';
    }finally{
      if(es){ es.close(); es = null; }
    }
  });
  es.onerror = (ev)=>{
    // show network/stream error
    console.error('Stream error:', ev);
    $('info').textContent = 'Stream error or connection closed';
    if(es){ es.close(); es = null; }
  };
});
