const $ = (id) => document.getElementById(id);

let searchController = null;

async function search(q) {
  if (!q || q.length < 3) return [];

  // Cancel any pending search
  if (searchController) {
    searchController.abort();
  }
  searchController = new AbortController();

  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, {
      signal: searchController.signal,
    });
    if (!res.ok) return [];
    return await res.json();
  } catch (err) {
    if (err.name === "AbortError") return null; // Request was cancelled
    console.error("Search error:", err);
    return [];
  }
}

function renderSuggestions(container, items) {
  container.innerHTML = "";
  if (!items || items.length === 0) {
    // show explicit no-matches message when user typed something
    const input = container.previousElementSibling;
    if (input && input.value && input.value.trim().length >= 3) {
      const no = document.createElement("div");
      no.className = "suggest";
      no.style.opacity = "0.7";
      no.textContent = "No matches";
      container.appendChild(no);
    }
    return;
  }
  items.slice(0, 5).forEach((it) => {
    const div = document.createElement("div");
    div.className = "suggest";
    div.textContent = `${it.name} (${it.id64})`;
    div.addEventListener("click", () => {
      const input = container.previousElementSibling;
      input.value = it.name;
      container.innerHTML = "";
    });
    container.appendChild(div);
  });
}

function setupSuggestionInput(inputId, suggestionId, checkCoords = false) {
  let timer = null;
  $(inputId).addEventListener("input", (e) => {
    clearTimeout(timer);
    const v = e.target.value.trim();
    if (checkCoords && v.includes(",")) {
      $(suggestionId).innerHTML = "";
      return;
    }
    timer = setTimeout(async () => {
      if (v.length < 2) {
        $(suggestionId).innerHTML = "";
        return;
      }
      const items = await search(v);
      if (items === null) return; // Stale request, do nothing
      renderSuggestions($(suggestionId), items);
    }, 500);
  });
}

setupSuggestionInput("source", "src-suggestions");
setupSuggestionInput("target", "tgt-suggestions");
setupSuggestionInput("near", "near-suggestions", true);

// Star Type Selector Implementation
const ALL_STAR_TYPES = [
  "A (Blue-White super giant) Star", "A (Blue-White) Star", "Ammonia world",
  "B (Blue-White super giant) Star", "B (Blue-White) Star", "Black Hole",
  "C Star", "CJ Star", "CN Star", "Class I gas giant", "Class II gas giant",
  "Class III gas giant", "Class IV gas giant", "Class V gas giant",
  "Earth-like world", "F (White super giant) Star", "F (White) Star",
  "G (White-Yellow super giant) Star", "G (White-Yellow) Star",
  "Gas giant with ammonia-based life", "Gas giant with water-based life",
  "Helium gas giant", "Helium-rich gas giant", "Herbig Ae/Be Star",
  "High metal content world", "Icy body", "K (Yellow-Orange giant) Star",
  "K (Yellow-Orange) Star", "L (Brown dwarf) Star", "M (Red dwarf) Star",
  "M (Red giant) Star", "M (Red super giant) Star", "MS-type Star",
  "Metal-rich body", "Neutron Star", "O (Blue-White) Star", "Rocky Ice world",
  "Rocky body", "S-type Star", "Supermassive Black Hole", "T (Brown dwarf) Star",
  "T Tauri Star", "Water giant", "Water world", "White Dwarf (D) Star",
  "White Dwarf (DA) Star", "White Dwarf (DAB) Star", "White Dwarf (DAV) Star",
  "White Dwarf (DAZ) Star", "White Dwarf (DB) Star", "White Dwarf (DBV) Star",
  "White Dwarf (DBZ) Star", "White Dwarf (DC) Star", "White Dwarf (DCV) Star",
  "White Dwarf (DQ) Star", "Wolf-Rayet C Star", "Wolf-Rayet N Star",
  "Wolf-Rayet NC Star", "Wolf-Rayet O Star", "Wolf-Rayet Star",
  "Y (Brown dwarf) Star"
];

let selectedStarTypes = new Set();

function renderChips() {
  const container = $('selected-chips');
  container.innerHTML = '';
  selectedStarTypes.forEach(type => {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.textContent = type;
    const remove = document.createElement('span');
    remove.className = 'remove';
    remove.textContent = '×';
    remove.onclick = () => {
      selectedStarTypes.delete(type);
      renderChips();
    };
    chip.appendChild(remove);
    container.appendChild(chip);
  });
}

function updateStarDropdown(q) {
  const dd = $('star-dropdown');
  dd.innerHTML = '';
  if (!q) {
    dd.classList.add('hidden');
    return;
  }
  const filtered = ALL_STAR_TYPES.filter(t => 
    t.toLowerCase().includes(q.toLowerCase()) && !selectedStarTypes.has(t)
  ).slice(0, 10);

  if (filtered.length === 0) {
    dd.classList.add('hidden');
    return;
  }

  filtered.forEach(t => {
    const div = document.createElement('div');
    div.textContent = t;
    div.onclick = () => {
      selectedStarTypes.add(t);
      $('star-search').value = '';
      dd.classList.add('hidden');
      renderChips();
    };
    dd.appendChild(div);
  });
  dd.classList.remove('hidden');
}

$('star-search').addEventListener('input', (e) => {
  updateStarDropdown(e.target.value.trim());
});

$('star-search').addEventListener('focus', (e) => {
  updateStarDropdown(e.target.value.trim());
});

document.addEventListener('click', (e) => {
  if (!e.target.closest('.star-selector')) {
    $('star-dropdown').classList.add('hidden');
  }
});

const PRESETS = {
  'kgbfoam': ["K (Yellow-Orange) Star", "G (White-Yellow) Star", "B (Blue-White) Star", "F (White) Star", "O (Blue-White) Star", "A (Blue-White) Star", "M (Red dwarf) Star"],
  'neutron': ["Neutron Star", "White Dwarf (D) Star", "White Dwarf (DA) Star", "White Dwarf (DAB) Star", "White Dwarf (DAV) Star", "White Dwarf (DAZ) Star", "White Dwarf (DB) Star", "White Dwarf (DBV) Star", "White Dwarf (DBZ) Star", "White Dwarf (DC) Star", "White Dwarf (DCV) Star", "White Dwarf (DQ) Star"],
  'exotic': ["Black Hole", "Supermassive Black Hole", "Wolf-Rayet Star", "Wolf-Rayet C Star", "Wolf-Rayet N Star", "Wolf-Rayet NC Star", "Wolf-Rayet O Star", "Herbig Ae/Be Star"]
};

$('preset-kgbfoam').onclick = () => {
  PRESETS.kgbfoam.forEach(t => selectedStarTypes.add(t));
  renderChips();
};
$('preset-neutron').onclick = () => {
  PRESETS.neutron.forEach(t => selectedStarTypes.add(t));
  renderChips();
};
$('preset-exotic').onclick = () => {
  PRESETS.exotic.forEach(t => selectedStarTypes.add(t));
  renderChips();
};
$('clear-types').onclick = () => {
  selectedStarTypes.clear();
  renderChips();
};

$('reverse').addEventListener('click', ()=>{
  const s = $('source').value;
  $('source').value = $('target').value;
  $('target').value = s;
});

let es = null;
let lastResult = null;
let currentParams = {};

function renderPath(data, maxHop) {
  const list = $('path-list');
  list.innerHTML = '';
  data.path.forEach((p, i)=>{
    const li = document.createElement('li');
    const strong = document.createElement('strong');
    strong.textContent = `${i+1}) ${p.name}`;
    li.appendChild(strong);
    const meta = document.createTextNode(` ${p.id64} (${p.coords.x.toFixed(1)}, ${p.coords.y.toFixed(1)}, ${p.coords.z.toFixed(1)}) ${p.mainStar || ''} hop=${p.hop_dist.toFixed(1)} `);
    li.appendChild(meta);
    if(p.needs_permit){
      const warn = document.createElement('strong');
      warn.textContent = ' [Permit locked]';
      li.appendChild(warn);
    }
    if(p.hop_dist > maxHop){
      const warn = document.createElement('strong');
      warn.textContent = ' [Exceeds max hop]';
      warn.style.color = 'red';
      li.appendChild(warn);
    }
    li.style.cursor = 'pointer';
    li.title = 'Click to copy system name';
    li.addEventListener('click', async ()=>{
      // Clear previous highlight
      document.querySelectorAll('#path-list li').forEach(el => el.classList.remove('highlight'));
      li.classList.add('highlight');

      const txt = p.name || '';
      try{
        if(navigator.clipboard && navigator.clipboard.writeText){
          await navigator.clipboard.writeText(txt);
        }else{
          const ta = document.createElement('textarea');
          ta.value = txt;
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
        }
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

$('find').addEventListener('click', async ()=>{
  const source = $('source').value.trim();
  const target = $('target').value.trim();
  const max_hop = parseFloat($('max-hop').value) || 400;
  const neutron_highway = $('neutron-highway').checked;
  
  currentParams = {source, target, max_hop, neutron_highway};

  // basic validation
  if(!source || !target){
    $('info').textContent = 'Enter both source and target';
    return;
  }

  $('info').textContent = 'Searching...';
  $('path-list').innerHTML = '';
  $('save-container').style.display = 'none';
  lastResult = null;

  // close previous EventSource if any
  if(es){
    es.close();
    es = null;
  }
  const params = new URLSearchParams({source, target, max_hop, neutron_highway});
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
        $('info').textContent = `Total: ${data.total.toFixed(1)} ly | Direct: ${data.direct.toFixed(1)} ly | Diff: +${data.diff_pct.toFixed(1)}%`;
        lastResult = data;
        $('save-container').style.display = 'block';
        renderPath(data, max_hop);
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

function updateSavedRoutesDropdown() {
  const select = $('saved-routes-list');
  select.innerHTML = '';
  const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
  const names = Object.keys(routes).sort();
  if (names.length === 0) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = '-- No saved routes --';
    select.appendChild(opt);
  } else {
    names.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    });
  }
}

$('save-route').addEventListener('click', () => {
  if (!lastResult) return;
  const name = `${currentParams.source} -> ${currentParams.target} (${currentParams.max_hop}ly)`;
  const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
  routes[name] = {
    params: currentParams,
    result: lastResult,
    timestamp: Date.now()
  };
  localStorage.setItem('plotter_routes', JSON.stringify(routes));
  updateSavedRoutesDropdown();
  $('info').textContent = `Route saved: ${name}`;
});

$('load-route').addEventListener('click', () => {
  const name = $('saved-routes-list').value;
  if (!name) return;
  const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
  const route = routes[name];
  if (route) {
    $('source').value = route.params.source;
    $('target').value = route.params.target;
    $('max-hop').value = route.params.max_hop;
    currentParams = route.params;
    lastResult = route.result;
    
    $('info').textContent = `Loaded: Total: ${lastResult.total.toFixed(1)} ly | Direct: ${lastResult.direct.toFixed(1)} ly | Diff: +${lastResult.diff_pct.toFixed(1)}%`;
    $('save-container').style.display = 'block';
    renderPath(lastResult, route.params.max_hop);
  }
});

$('delete-route').addEventListener('click', () => {
  const name = $('saved-routes-list').value;
  if (!name) return;
  if (confirm(`Delete saved route "${name}"?`)) {
    const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
    delete routes[name];
    localStorage.setItem('plotter_routes', JSON.stringify(routes));
    updateSavedRoutesDropdown();
  }
});

$('export-route').addEventListener('click', () => {
  const name = $('saved-routes-list').value;
  if (!name) return;
  const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
  const route = routes[name];
  if (route) {
    const blob = new Blob([JSON.stringify(route, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name.replace(/[^a-z0-9]/gi, '_')}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
});

$('import-btn').addEventListener('click', () => {
  $('import-file').click();
});

$('import-file').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    try {
      const data = JSON.parse(ev.target.result);
      const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
      
      // Check if it's a single route or multiple
      if (data.params && data.result) {
        // Single route
        const name = `${data.params.source} -> ${data.params.target} (${data.params.max_hop}ly) [Imported]`;
        routes[name] = data;
      } else {
        // Assume collection of routes
        Object.assign(routes, data);
      }
      
      localStorage.setItem('plotter_routes', JSON.stringify(routes));
      updateSavedRoutesDropdown();
      alert('Routes imported successfully');
    } catch (err) {
      alert('Failed to import: Invalid JSON file');
      console.error(err);
    }
    e.target.value = ''; // Reset input
  };
  reader.readAsText(file);
});

$('find-nearest').addEventListener('click', async ()=>{
  const near = $('near').value.trim();
  let types = Array.from(selectedStarTypes).join(',');
  if(!near){
    $('info').textContent = 'Enter reference point';
    return;
  }
  $('info').textContent = 'Searching...';
  $('path-list').innerHTML = '';
  $('save-container').style.display = 'none';
  lastResult = null;
  
  try {
    const params = new URLSearchParams({near, types});
    const res = await fetch(`/api/nearest?${params.toString()}`);
    const data = await res.json();
    console.log('Nearest Result:', data);
    if(data.error){
      $('info').textContent = data.error;
    }else{
      $('info').textContent = `Found: ${data.name} | Distance: ${data.dist.toFixed(1)}ly | Star: ${data.mainStar}`;
      const li = document.createElement('li');
      li.style.cursor = 'pointer';
      li.title = 'Click to copy system name';
      const strong = document.createElement('strong');
      strong.textContent = data.name;
      li.appendChild(strong);
      const meta = document.createTextNode(` id=${data.id64} coords=(${data.coords.x.toFixed(1)}, ${data.coords.y.toFixed(1)}, ${data.coords.z.toFixed(1)}) star=${data.mainStar}`);
      li.appendChild(meta);
      
      li.addEventListener('click', async () => {
        document.querySelectorAll('#path-list li').forEach(el => el.classList.remove('highlight'));
        li.classList.add('highlight');
        try {
          await navigator.clipboard.writeText(data.name);
          $('info').textContent = `Copied: ${data.name}`;
        } catch(e) {}
      });
      
      $('path-list').appendChild(li);
    }
  } catch(e) {
    console.error(e);
    $('info').textContent = 'Error during search';
  }
});

updateSavedRoutesDropdown();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(reg => {
      console.log('SW registered:', reg);
      
      // Check for updates on load
      reg.update();

      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing;
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            // New content is available; please refresh.
            if (confirm('A new version of the Plotter is available. Update now?')) {
              location.reload();
            }
          }
        });
      });
    }).catch(err => {
      console.log('SW registration failed:', err);
    });
  });

  // Handle controller change (e.g. after skipWaiting)
  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  });
}
