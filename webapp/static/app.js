import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = (id) => document.getElementById(id);

class GalaxyView {
  constructor(containerId) {
    this.container = $(containerId);
    this.init();
  }

  init() {
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x020617);
    
    this.camera = new THREE.PerspectiveCamera(60, this.container.clientWidth / 400, 1, 1000000);
    this.camera.position.set(0, 1000, 2000);
    
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(this.container.clientWidth, 400);
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.container.appendChild(this.renderer.domElement);
    
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    
    // Add grid for galactic plane
    const grid = new THREE.GridHelper(100000, 100, 0x1e293b, 0x0f172a);
    grid.position.set(0, 0, -25900);
    this.scene.add(grid);

    // --- Galactic Plane Glow ---
    const planeSize = 400000; // covers the whole bubble
    const glowGeometry = new THREE.PlaneGeometry(planeSize, planeSize);

    var glowMaterial = new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        depthTest: false,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        uniforms: {
            uColor: { value: new THREE.Color(0x406080) },
            uIntensity: { value: 1.2 },
            uFalloff: { value: 0.00005 } // lower = larger glow
        },
        vertexShader: `
            varying vec2 vUvScaled;
            void main() {
                // uv is 0..1, shift to -0.5..0.5
                vec2 centered = uv - 0.5;

                // scale to galaxy size (200k LY plane)
                vUvScaled = centered * 200000.0;

                gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
            }
        `,
        fragmentShader: `
            varying vec2 vUvScaled;
            uniform vec3 uColor;
            uniform float uIntensity;
            uniform float uFalloff;

            void main() {
                float dist = length(vUvScaled);

                // exponential falloff in LY
                float alpha = uIntensity * exp(-dist * uFalloff);

                gl_FragColor = vec4(uColor, alpha);
            }
        `
    });


    const glowPlane = new THREE.Mesh(glowGeometry, glowMaterial);
    glowPlane.rotation.x = -Math.PI / 2; // horizontal
    glowPlane.position.set(0, 0, -25900); // Sagittarius A*
    this.scene.add(glowPlane);
    // allow easy manipulation from console
    window.galaxyGlow = glowMaterial;
    window.galaxyGlowPlane = glowPlane;

    this.route = new THREE.Group();
    this.scene.add(this.route);

    this.labels = new THREE.Group();
    this.scene.add(this.labels);

    this.anchors = new THREE.Group();
    this.scene.add(this.anchors);
    this.anchorNames = ['Sol', 'Colonia', 'Sagittarius A*', 'Beagle Point'];
    this.initAnchors();

    window.addEventListener('resize', () => this.onResize());
    this.animate();
  }

  initAnchors() {
    const systems = [
      { name: 'Sol', x: 0, y: 0, z: 0 },
      { name: 'Colonia', x: -9530.5, y: -910.3, z: 19808.1 },
      { name: 'Sagittarius A*', x: 25.2, y: -20.9, z: 25900.0 },
      { name: 'Beagle Point', x: -1111.5625, y: -134.21875, z: 65269.75 },
    ];

    systems.forEach(s => {
      const sprite = this.createLabel(s.name, s.x, s.y, -s.z, '#475569');
      this.anchors.add(sprite);
      
      // Add a small point for the anchor
      const geom = new THREE.SphereGeometry(50, 8, 8);
      const mat = new THREE.MeshBasicMaterial({ color: 0x475569, transparent: true, opacity: 0.5 });
      const mesh = new THREE.Mesh(geom, mat);
      mesh.position.set(s.x, s.y, -s.z);
      this.anchors.add(mesh);
    });
  }

  createLabel(text, x, y, z, color = '#22d3ee') {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 512;
    canvas.height = 128;
    
    ctx.font = 'Bold 48px Inter, Arial, sans-serif';
    ctx.fillStyle = color;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    
    // Draw text with a subtle glow/shadow for readability
    ctx.shadowColor = 'rgba(0,0,0,0.8)';
    ctx.shadowBlur = 8;
    ctx.fillText(text, 256, 64);

    const texture = new THREE.CanvasTexture(canvas);
    const material = new THREE.SpriteMaterial({ map: texture, transparent: true });
    const sprite = new THREE.Sprite(material);
    sprite.position.set(x, y + 600, z); // Offset label above point
    sprite.scale.set(5000, 1250, 1);
    return sprite;
  }

  onResize() {
    this.camera.aspect = this.container.clientWidth / 400;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(this.container.clientWidth, 400);
  }

  animate() {
    requestAnimationFrame(() => this.animate());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  clear() {
    while(this.route.children.length > 0) {
      const child = this.route.children[0];
      child.geometry.dispose();
      child.material.dispose();
      this.route.remove(child);
    }
    while(this.labels.children.length > 0) {
      const child = this.labels.children[0];
      if (child.material && child.material.map) child.material.map.dispose();
      if (child.material) child.material.dispose();
      this.labels.remove(child);
    }
  }

  addRoute(path) {
    if (!path || path.length === 0) return;
    const points = [];
    path.forEach(node => {
      // Negate Z because Elite Z+ (North) should point 'Away' (Three.js Z-)
      points.push(new THREE.Vector3(node.coords.x, node.coords.y, -node.coords.z));
    });

    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    const material = new THREE.LineBasicMaterial({
      color: 0x22d3ee,
      linewidth: 3,
      depthTest: true
    });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 1;
    this.route.add(line);

    // Add glowing spheres for route nodes
    path.forEach(node => {
      const sphereGeom = new THREE.SphereGeometry(25, 8, 8);
      const color = node.is_neutron ? 0x22d3ee : 0x3b82f6;
      const sphereMat = new THREE.MeshBasicMaterial({ 
        color: color,
        transparent: true,
        opacity: 0.9
      });
      const sphere = new THREE.Mesh(sphereGeom, sphereMat);
      sphere.position.set(node.coords.x, node.coords.y, -node.coords.z);
      sphere.renderOrder = 2;
      this.route.add(sphere);
    });

    // Add labels for source and target with deduplication
    const source = path[0];
    const target = path[path.length - 1];

    if (!this.anchorNames.includes(source.name)) {
      this.labels.add(this.createLabel(source.name, source.coords.x, source.coords.y, -source.coords.z));
    }
    
    if (target !== source && !this.anchorNames.includes(target.name)) {
      this.labels.add(this.createLabel(target.name, target.coords.x, target.coords.y, -target.coords.z));
    }

    this.frameRoute(path);
  }

  frameRoute(path) {
    if (!path || path.length === 0) {
      this.camera.position.set(0, 1000, 2000);
      this.controls.target.set(0, 0, 0);
      return;
    }

    const bbox = new THREE.Box3();
    path.forEach(node => {
      bbox.expandByPoint(new THREE.Vector3(node.coords.x, node.coords.y, -node.coords.z));
    });

    const center = new THREE.Vector3();
    bbox.getCenter(center);
    const size = new THREE.Vector3();
    bbox.getSize(size);
    const maxDim = Math.max(size.x, size.y, size.z);
    
    const zoomAmount = Math.max(2000, maxDim * 1.5);
    this.camera.position.set(center.x, center.y + zoomAmount * 0.5, center.z + zoomAmount);
    this.controls.target.copy(center);
  }
}

let galaxyView = null;

// Tab Switching
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tabId = btn.getAttribute('data-tab');
    
    // Update buttons
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    
    // Update content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    $(`${tabId}-tab`).classList.add('active');
    
    // Auto-hide/show results based on tab
    if (tabId === 'home') {
      $('results').classList.add('hidden');
    } else if (lastResult || $('path-list').children.length > 0) {
      $('results').classList.remove('hidden');
    }
  });
});

function handlePlottingError(data) {
  if (data.error === 'limit_exceeded') {
    $('info').innerHTML = `<span style="color: #b91c1c; font-weight: bold;">Route exceeds limit of ${data.limit.toLocaleString()} ly</span><br/>Direct distance: ${data.dist.toFixed(0)} ly`;
    if (data.suggestion) {
      const div = document.createElement('div');
      div.className = 'suggestion-box';
      const typeStr = data.is_neutron ? 'Neutron Star' : 'system';
      div.innerHTML = `<span>Try plotting to a ${typeStr} closer to the limit:</span><br/><strong>${data.suggestion.name}</strong> (~25k ly away)`;
      const btn = document.createElement('button');
      btn.textContent = 'Use as Target';
      btn.style.marginLeft = '12px';
      btn.onclick = () => {
        const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
        if (activeTab === 'carrier') {
          $('carrier-target').value = data.suggestion.name;
          $('carrier-find').click();
        } else {
          $('target').value = data.suggestion.name;
          $('find').click();
        }
      };
      div.appendChild(btn);
      $('info').appendChild(div);
    }
  } else {
    $('info').textContent = data.error;
  }
}

$('carrier-find').addEventListener('click', async ()=>{
  if (!(await ensureBackendReady())) return;

  const source = $('carrier-source').value.trim();
  const target = $('carrier-target').value.trim();
  const max_hop = parseFloat($('carrier-max-hop').value) || 500;
  const neutron_highway = false; // Carriers don't use neutron highway for plotting
  
  currentParams = {source, target, max_hop, neutron_highway};

  if(!source || !target){
    $('info').textContent = 'Enter both source and target';
    return;
  }

  $('info').textContent = 'Searching...';
  $('results').classList.remove('hidden');
  $('search-progress').classList.remove('hidden');
  $('path-list').innerHTML = '';
  $('save-container').style.display = 'none';
  lastResult = null;

  if(es){ es.close(); es = null; }
  if(galaxyView) galaxyView.clear();

  const params = new URLSearchParams({source, target, max_hop, neutron_highway});
  es = new EventSource(`/api/path/stream?${params.toString()}`);
  es.addEventListener('progress', (ev)=>{
    try{
      $('info').textContent = ev.data;
    }catch(e){/*ignore*/}
  });
  es.addEventListener('result', (ev)=>{
    $('search-progress').classList.add('hidden');
    try{
      const data = JSON.parse(ev.data);
      if(data.error){
        handlePlottingError(data);
      }else{
        lastSuccessTime = Date.now();
        lastResult = data;
        $('save-container').style.display = 'block';
        renderPath(data, max_hop, getCarrierParams());
      }
    }catch(e){
      $('info').textContent = 'Error parsing result';
    }finally{
      if(es){ es.close(); es = null; }
    }
  });
  es.onerror = (ev)=>{
    $('search-progress').classList.add('hidden');
    $('info').textContent = 'Stream error or connection closed';
    if(es){ es.close(); es = null; }
  };
});

// Theme Toggle Logic
function setTheme(theme, persist = true) {
  document.documentElement.setAttribute('data-theme', theme);
  if (persist) {
    localStorage.setItem('plotter_theme', theme);
  }
}

function initTheme() {
  const saved = localStorage.getItem('plotter_theme');
  if (saved) {
    setTheme(saved, false);
  } else {
    const prefersLight = window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
    setTheme(prefersLight ? 'light' : 'dark', false);
  }
}

// Listen for system theme changes if no manual override
if (window.matchMedia) {
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', e => {
    if (!localStorage.getItem('plotter_theme')) {
      setTheme(e.matches ? 'light' : 'dark', false);
    }
  });
}

$('theme-toggle').addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme');
  setTheme(current === 'light' ? 'dark' : 'light');
});

initTheme();

function showToast(message, duration = 3000) {
  const container = $('toast-container');
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('out');
    toast.addEventListener('animationend', () => toast.remove());
  }, duration);
}

let lastSuccessTime = 0;
let isWarmingUp = false;
let warmupPollInterval = null;
let warmupCountdownInterval = null;

async function fetchWithTimeout(resource, options = {}) {
  const { timeout = 8000, signal } = options;
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  
  // If an external signal is provided, listen for it to abort our internal controller
  if (signal) {
    if (signal.aborted) controller.abort();
    signal.addEventListener('abort', () => controller.abort());
  }

  try {
    const response = await fetch(resource, {
      ...options,
      signal: controller.signal
    });
    return response;
  } catch (error) {
    if (error.name === 'AbortError') {
      if (signal && signal.aborted) {
        throw error;
      }
      const timeoutError = new Error('Request timed out');
      timeoutError.name = 'TimeoutError';
      throw timeoutError;
    }
    throw error;
  } finally {
    clearTimeout(id);
  }
}

function updateWarmupUI(seconds) {
  const bar = $('backend-status');
  bar.className = 'status-bar warming';
  bar.querySelector('.status-text').textContent = `Backend is warming up... Ready in approx. ${seconds}s`;
  
  const progress = bar.querySelector('.progress-bar');
  const pct = Math.max(0, Math.min(100, ((60 - seconds) / 60) * 100));
  progress.style.width = `${pct}%`;
  
  bar.classList.remove('hidden');
}

function onBackendReady() {
  isWarmingUp = false;
  lastSuccessTime = Date.now();
  clearInterval(warmupPollInterval);
  clearInterval(warmupCountdownInterval);
  
  const bar = $('backend-status');
  bar.className = 'status-bar ready';
  bar.querySelector('.status-text').textContent = 'Backend Ready!';
  bar.querySelector('.progress-bar').style.width = '100%';
  
  $('find').disabled = false;
  $('find-nearest').disabled = false;
  
  setTimeout(() => {
    if (!isWarmingUp) bar.classList.add('hidden');
  }, 3000);
}

function startWarmupSequence() {
  if (isWarmingUp) return;
  isWarmingUp = true;
  console.log("Backend warmup sequence started");
  
  $('find').disabled = true;
  $('find-nearest').disabled = true;
  
  let seconds = 60;
  updateWarmupUI(seconds);
  
  warmupCountdownInterval = setInterval(() => {
    seconds = Math.max(0, seconds - 1);
    if (isWarmingUp) updateWarmupUI(seconds);
  }, 1000);
  
  warmupPollInterval = setInterval(async () => {
    try {
      const res = await fetchWithTimeout('/api/health', { timeout: 2000 });
      if (res.ok) {
        onBackendReady();
      }
    } catch (e) {
      // Still warming up
    }
  }, 3000);
}

async function ensureBackendReady() {
  if (Date.now() - lastSuccessTime < 300000) {
    return true;
  }
  
  try {
    const res = await fetchWithTimeout('/api/health', { timeout: 2000 });
    if (res.ok) {
      lastSuccessTime = Date.now();
      return true;
    }
  } catch (e) {
  }
  
  startWarmupSequence();
  return false;
}

let searchController = null;

async function search(q) {
  if (!q || q.length < 3) return [];

  if (searchController) {
    searchController.abort();
  }
  searchController = new AbortController();

  try {
    const res = await fetchWithTimeout(`/api/search?q=${encodeURIComponent(q)}`, {
      signal: searchController.signal,
      timeout: 3000 
    });
    if (res.status === 502 || res.status === 504) {
      startWarmupSequence();
      return [];
    }
    if (!res.ok) return [];
    lastSuccessTime = Date.now();
    return await res.json();
  } catch (err) {
    if (err.name === "AbortError") {
      return null;
    }
    startWarmupSequence();
    return [];
  }
}

function renderSuggestions(container, items) {
  container.innerHTML = "";
  if (!items || items.length === 0) {
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
      if (items === null) return; 
      renderSuggestions($(suggestionId), items);
    }, 500);
  });
}

setupSuggestionInput("source", "src-suggestions");
setupSuggestionInput("target", "tgt-suggestions");
setupSuggestionInput("near", "near-suggestions", true);
setupSuggestionInput("carrier-source", "carrier-src-suggestions");
setupSuggestionInput("carrier-target", "carrier-tgt-suggestions");

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

$('carrier-reverse').addEventListener('click', ()=>{
  const s = $('carrier-source').value;
  $('carrier-source').value = $('carrier-target').value;
  $('carrier-target').value = s;
});

let es = null;
let lastResult = null;
let currentParams = {};

function renderPath(data, maxHop, carrierParams = null) {
  const list = $('path-list');
  list.innerHTML = '';

  if (galaxyView) {
    galaxyView.addRoute(data.path);
  }
  
  let totalFuel = 0;
  let currentTritium = carrierParams ? carrierParams.tritium : 0;
  let showFuel = carrierParams && !carrierParams.isEmpty;

  const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
  const savedRouteName = $('saved-routes-list').value;
  const isCarrier = activeTab === 'carrier' || (savedRouteName && savedRouteName.includes('[Carrier]'));

  data.path.forEach((p, i)=>{
    const li = document.createElement('li');
    const strong = document.createElement('strong');
    strong.textContent = p.name;
    li.appendChild(strong);
    
    let fuelText = '';
    if (showFuel && i > 0) {
      const fuel = Math.ceil(5 + p.hop_dist * (carrierParams.cargo + currentTritium + 25000) / 200000);
      totalFuel += fuel;
      currentTritium -= fuel;
      fuelText = ` | ⛽ ${fuel}T (Rem: ${currentTritium}T)`;
    }

    const starInfo = isCarrier ? '' : ` ${p.mainStar || ''}`;
    const meta = document.createTextNode(` ${p.id64} (${p.coords.x.toFixed(1)}, ${p.coords.y.toFixed(1)}, ${p.coords.z.toFixed(1)})${starInfo} hop=${p.hop_dist.toFixed(1)}${fuelText} `);
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
        showToast(`Copied: ${txt}`);
      }catch(e){
        showToast(`Copy failed`);
      }
    });
    list.appendChild(li);
  });

  if (showFuel || isCarrier) {
    const actualHops = data.path.length - 1;
    const perfectHops = Math.ceil(data.total / 500);
    
    $('info').innerHTML = '';
    $('info').appendChild(document.createTextNode(`Total: ${data.total.toFixed(1)} ly | Direct: ${data.direct.toFixed(1)} ly`));
    
    const efficiencySpan = document.createElement('span');
    efficiencySpan.textContent = ` | Hops: ${actualHops} vs ${perfectHops} (Perfect)`;
    efficiencySpan.title = "Theoretical minimum number of jumps if every hop was exactly 500ly (except the last).";
    efficiencySpan.style.cursor = 'help';
    efficiencySpan.style.borderBottom = '1px dotted #888';
    efficiencySpan.style.marginLeft = '4px';
    $('info').appendChild(efficiencySpan);

    if (showFuel) {
      $('info').appendChild(document.createTextNode(` | Fuel: ${totalFuel} T`));
    }
    
    if (showFuel && currentTritium < 0) {
      const warn = document.createElement('span');
      warn.style.color = 'red';
      warn.style.fontWeight = 'bold';
      warn.style.marginLeft = '8px';
      warn.textContent = '[Out of fuel!]';
      $('info').appendChild(warn);
    }
  } else {
    $('info').textContent = `Total: ${data.total.toFixed(1)} ly | Direct: ${data.direct.toFixed(1)} ly | Diff: +${data.diff_pct.toFixed(1)}%`;
  }
}

function getCarrierParams() {
  const cargoStr = $('carrier-cargo').value.trim();
  const tritiumStr = $('carrier-tritium').value.trim();
  
  if (cargoStr === '' && tritiumStr === '') return { cargo: 0, tritium: 0, isEmpty: true };

  let cargo = parseFloat(cargoStr) || 0;
  let tritium = parseFloat(tritiumStr) || 0;
  
  if (cargo < 0) cargo = 0;
  if (cargo > 25000) cargo = 25000;
  if (tritium < 0) tritium = 0;
  if (tritium > 1000) tritium = 1000;
  
  return { cargo, tritium, isEmpty: false };
}

$('carrier-cargo').addEventListener('input', () => {
  if (lastResult) {
    renderPath(lastResult, currentParams.max_hop, getCarrierParams());
  }
});
$('carrier-tritium').addEventListener('input', () => {
  if (lastResult) {
    renderPath(lastResult, currentParams.max_hop, getCarrierParams());
  }
});

$('find').addEventListener('click', async ()=>{
  if (!(await ensureBackendReady())) return;

  const source = $('source').value.trim();
  const target = $('target').value.trim();
  const max_hop = parseFloat($('max-hop').value) || 400;
  const neutron_highway = $('neutron-highway').checked;
  
  currentParams = {source, target, max_hop, neutron_highway};

  if(!source || !target){
    $('info').textContent = 'Enter both source and target';
    return;
  }

  $('info').textContent = 'Searching...';
  $('results').classList.remove('hidden');
  $('search-progress').classList.remove('hidden');
  $('path-list').innerHTML = '';
  $('save-container').style.display = 'none';
  lastResult = null;

  if(es){
    es.close();
    es = null;
  }
  if(galaxyView) galaxyView.clear();

  const params = new URLSearchParams({source, target, max_hop, neutron_highway});
  es = new EventSource(`/api/path/stream?${params.toString()}`);
  es.addEventListener('progress', (ev)=>{
    try{
      const txt = ev.data;
      $('info').textContent = txt;
    }catch(e){/*ignore*/}
  });
  es.addEventListener('result', (ev)=>{
    $('search-progress').classList.add('hidden');
    try{
      const data = JSON.parse(ev.data);
      if(data.error){
        handlePlottingError(data);
      }else{
        lastSuccessTime = Date.now();
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
    $('search-progress').classList.add('hidden');
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
  const neutronFlag = currentParams.neutron_highway ? ' [Neutron]' : '';
  const activeTab = document.querySelector('.tab-btn.active').getAttribute('data-tab');
  const carrierFlag = activeTab === 'carrier' ? ' [Carrier]' : '';
  const name = `${currentParams.source} -> ${currentParams.target} (${currentParams.max_hop}ly)${neutronFlag}${carrierFlag}`;
  const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
  const carrierParams = activeTab === 'carrier' ? getCarrierParams() : null;

  routes[name] = {
    params: currentParams,
    carrierParams: carrierParams,
    result: lastResult,
    timestamp: Date.now()
  };
  localStorage.setItem('plotter_routes', JSON.stringify(routes));
  updateSavedRoutesDropdown();
  showToast(`Route saved: ${name}`);
});

$('load-route').addEventListener('click', () => {
  const name = $('saved-routes-list').value;
  if (!name) return;
  const routes = JSON.parse(localStorage.getItem('plotter_routes') || '{}');
  const route = routes[name];
  if (route) {
    if (name.includes('[Carrier]')) {
      $('carrier-source').value = route.params.source;
      $('carrier-target').value = route.params.target;
      $('carrier-max-hop').value = route.params.max_hop;
      if (route.carrierParams) {
        $('carrier-cargo').value = (route.carrierParams.cargo !== undefined && route.carrierParams.cargo !== null) ? route.carrierParams.cargo : '';
        $('carrier-tritium').value = (route.carrierParams.tritium !== undefined && route.carrierParams.tritium !== null) ? route.carrierParams.tritium : '';
      }
      document.querySelector('[data-tab="carrier"]').click();
    } else {
      $('source').value = route.params.source;
      $('target').value = route.params.target;
      $('max-hop').value = route.params.max_hop;
      if ($('neutron-highway')) {
        $('neutron-highway').checked = route.params.neutron_highway;
      }
      document.querySelector('[data-tab="plotter"]').click();
    }
    
    currentParams = { ...route.params };
    lastResult = route.result;
    
    $('results').classList.remove('hidden');
    $('save-container').style.display = 'block';
    if(galaxyView) galaxyView.clear();
    renderPath(lastResult, route.params.max_hop, getCarrierParams());
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
      if (data.params && data.result) {
        const name = `${data.params.source} -> ${data.params.target} (${data.params.max_hop}ly) [Imported]`;
        routes[name] = data;
      } else {
        Object.assign(routes, data);
      }
      localStorage.setItem('plotter_routes', JSON.stringify(routes));
      updateSavedRoutesDropdown();
      alert('Routes imported successfully');
    } catch (err) {
      alert('Failed to import: Invalid JSON file');
    }
    e.target.value = ''; 
  };
  reader.readAsText(file);
});
$('find-nearest').addEventListener('click', async ()=>{
  if (!(await ensureBackendReady())) return;

  const near = $('near').value.trim();
  let types = Array.from(selectedStarTypes).join(',');
  if(!near){
    $('info').textContent = 'Enter reference point';
    return;
  }
  $('info').textContent = 'Searching...';
  $('results').classList.remove('hidden');
  $('search-progress').classList.remove('hidden');
  $('path-list').innerHTML = '';
  $('save-container').style.display = 'none';
  lastResult = null;

  try {
    const params = new URLSearchParams({near, types});
    const res = await fetchWithTimeout(`/api/nearest?${params.toString()}`);
    $('search-progress').classList.add('hidden');
    if (res.status === 502 || res.status === 504) {
      startWarmupSequence();
      return;
    }
    const data = await res.json();
    if(data.error){
      $('info').textContent = data.error;
    }else{
      lastSuccessTime = Date.now();
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
          showToast(`Copied: ${data.name}`);
        } catch(e) {
          showToast(`Copy failed`);
        }
      });
      
      $('path-list').appendChild(li);
    }
  } catch(e) {
    $('search-progress').classList.add('hidden');
    $('info').textContent = 'Error during search';
  }
});

updateSavedRoutesDropdown();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(reg => {
      reg.update();
      reg.addEventListener('updatefound', () => {
        const newWorker = reg.installing;
        newWorker.addEventListener('statechange', () => {
          if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
            if (confirm('A new version of the Plotter is available. Update now?')) {
              location.reload();
            }
          }
        });
      });
    });
  });

  let refreshing = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (refreshing) return;
    refreshing = true;
    window.location.reload();
  });
}

// 3D Visualizer UI Handlers
$('toggle-3d').addEventListener('click', () => {
  $('visualizer-container').classList.remove('hidden');
  $('toggle-3d').classList.add('hidden');
  if (!galaxyView) {
    galaxyView = new GalaxyView('three-viewport');
  }
  if (lastResult) {
    galaxyView.clear();
    galaxyView.addRoute(lastResult.path);
  }
});

$('close-3d').addEventListener('click', () => {
  $('visualizer-container').classList.add('hidden');
  $('toggle-3d').classList.remove('hidden');
});

$('reset-camera').addEventListener('click', () => {
  if (galaxyView) {
    galaxyView.frameRoute(lastResult ? lastResult.path : null);
  }
});
