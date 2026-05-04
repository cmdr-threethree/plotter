const $ = (id) => document.getElementById(id);

async function search(q){
  if(!q) return [];
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
  if(!res.ok) return [];
  return await res.json();
}

function renderSuggestions(container, items){
  container.innerHTML = '';
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

$('find').addEventListener('click', async ()=>{
  const source = $('source').value.trim();
  const target = $('target').value.trim();
  const max_hop = parseFloat($('max-hop').value) || 40;
  const bucket_size = parseFloat($('bucket-size').value) || 50;
  $('info').textContent = 'Searching...';
  $('path-list').innerHTML = '';
  try{
    const res = await fetch('/api/path', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({source, target, max_hop, bucket_size})
    });
    if(!res.ok){
      const err = await res.json();
      $('info').textContent = err.error || 'No path';
      return;
    }
    const data = await res.json();
    $('info').textContent = `Total distance: ${data.total.toFixed(1)}`;
    const list = $('path-list');
    data.path.forEach((p, i)=>{
      const li = document.createElement('li');
      li.innerHTML = `<strong>${i+1}) ${p.name}</strong> id=${p.id64} coords=(${p.coords.x.toFixed(1)}, ${p.coords.y.toFixed(1)}, ${p.coords.z.toFixed(1)}) hop=${p.hop_dist.toFixed(1)} mainStar=${p.mainStar || ''}`;
      list.appendChild(li);
    });
  }catch(err){
    $('info').textContent = String(err);
  }
});
