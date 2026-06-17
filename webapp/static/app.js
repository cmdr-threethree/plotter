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
    
    const height = this.container.clientHeight || 400;
    this.camera = new THREE.PerspectiveCamera(60, this.container.clientWidth / height, 1, 1000000);
    this.camera.position.set(0, 1000, 2000);
    
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(this.container.clientWidth, height);
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
    const height = this.container.clientHeight || 400;
    this.camera.aspect = this.container.clientWidth / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(this.container.clientWidth, height);
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

const DEMO_ROUTE = {
  "params": {
    "source": "Sol",
    "target": "Colonia",
    "max_hop": 400,
    "neutron_highway": true
  },
  "result": {
    "path": [
      {
        "id64": 10477373803,
        "name": "Sol",
        "coords": {
          "x": 0,
          "y": 0,
          "z": 0
        },
        "mainStar": "G (White-Yellow) Star",
        "hop_dist": 0,
        "needs_permit": true
      },
      {
        "id64": 5532807773,
        "name": "Jackson's Lighthouse",
        "coords": {
          "x": 157,
          "y": -27,
          "z": -70
        },
        "mainStar": "Neutron Star",
        "hop_dist": 174,
        "needs_permit": false
      },
      {
        "id64": 151634584764,
        "name": "Lalande 25224",
        "coords": {
          "x": 22.28125,
          "y": 183.3125,
          "z": 64.65625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 283.7,
        "needs_permit": false
      },
      {
        "id64": 22712681061,
        "name": "PSR J1752-2806",
        "coords": {
          "x": -10.96875,
          "y": -6.84375,
          "z": 407.28125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 393.3,
        "needs_permit": false
      },
      {
        "id64": 5531763309,
        "name": "Nova Aquila No 3",
        "coords": {
          "x": -363.03125,
          "y": 3.3125,
          "z": 548.28125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 379.4,
        "needs_permit": false
      },
      {
        "id64": 1041168861635,
        "name": "B133 Sector DB-X d1-30",
        "coords": {
          "x": -490.78125,
          "y": -15.71875,
          "z": 881.40625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 357.3,
        "needs_permit": false
      },
      {
        "id64": 1109838006739,
        "name": "Col 359 Sector PU-F d11-32",
        "coords": {
          "x": -733.28125,
          "y": -17.875,
          "z": 1061.40625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 302,
        "needs_permit": false
      },
      {
        "id64": 1041084959211,
        "name": "Swoiwns BY-F d12-30",
        "coords": {
          "x": -943.84375,
          "y": -67.46875,
          "z": 1311.1875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 330.4,
        "needs_permit": false
      },
      {
        "id64": 1796965648907,
        "name": "Bleia Eohn DC-B d1-52",
        "coords": {
          "x": -1063.90625,
          "y": -61,
          "z": 1634.375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 344.8,
        "needs_permit": false
      },
      {
        "id64": 2277951654427,
        "name": "Bleia Eohn IO-X d2-66",
        "coords": {
          "x": -1279.5,
          "y": -60,
          "z": 1753.40625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 246.3,
        "needs_permit": false
      },
      {
        "id64": 1144063527475,
        "name": "Phylur NL-P d5-33",
        "coords": {
          "x": -1357.1875,
          "y": 12.5,
          "z": 2018.8125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 285.9,
        "needs_permit": false
      },
      {
        "id64": 285070068299,
        "name": "Phylur ZD-K d8-8",
        "coords": {
          "x": -1414.9375,
          "y": -6.3125,
          "z": 2285.09375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 273.1,
        "needs_permit": false
      },
      {
        "id64": 1968646900323,
        "name": "Aucopp ES-H d11-57",
        "coords": {
          "x": -1598.46875,
          "y": -55.90625,
          "z": 2465.25
        },
        "mainStar": "Neutron Star",
        "hop_dist": 261.9,
        "needs_permit": false
      },
      {
        "id64": 1418874309251,
        "name": "Drojeae HW-C d41",
        "coords": {
          "x": -1742.03125,
          "y": -78.3125,
          "z": 2834.75
        },
        "mainStar": "Neutron Star",
        "hop_dist": 397,
        "needs_permit": false
      },
      {
        "id64": 2552728881835,
        "name": "Drojeae CW-T d4-74",
        "coords": {
          "x": -1799.28125,
          "y": -107.375,
          "z": 3197.28125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 368.2,
        "needs_permit": false
      },
      {
        "id64": 422374771395,
        "name": "Drojeae LO-O d7-12",
        "coords": {
          "x": -1993.5625,
          "y": -129.1875,
          "z": 3460.375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 327.8,
        "needs_permit": false
      },
      {
        "id64": 869034593003,
        "name": "Drojeae ET-F d12-25",
        "coords": {
          "x": -2069.96875,
          "y": -107.8125,
          "z": 3843.09375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 390.9,
        "needs_permit": false
      },
      {
        "id64": 3033664555787,
        "name": "Blae Drye GX-A d1-88",
        "coords": {
          "x": -2239.125,
          "y": -149.46875,
          "z": 4179.53125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 378.9,
        "needs_permit": false
      },
      {
        "id64": 2312110050083,
        "name": "Blae Drye SP-V d3-67",
        "coords": {
          "x": -2276.59375,
          "y": -160.21875,
          "z": 4426.3125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 249.8,
        "needs_permit": false
      },
      {
        "id64": 4614195743563,
        "name": "Blae Drye LU-M d8-134",
        "coords": {
          "x": -2380.03125,
          "y": -131,
          "z": 4775.0625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 364.9,
        "needs_permit": false
      },
      {
        "id64": 697151998827,
        "name": "Blae Drye BO-F d12-20",
        "coords": {
          "x": -2504.25,
          "y": -246.875,
          "z": 5109.90625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 375.5,
        "needs_permit": false
      },
      {
        "id64": 1556145441675,
        "name": "Gria Drye HN-A d1-45",
        "coords": {
          "x": -2499.53125,
          "y": -293,
          "z": 5441.875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 335.2,
        "needs_permit": false
      },
      {
        "id64": 2621263760299,
        "name": "Pyraleau NH-T d4-76",
        "coords": {
          "x": -2704.84375,
          "y": -351.125,
          "z": 5767.6875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 389.5,
        "needs_permit": false
      },
      {
        "id64": 2208913329099,
        "name": "Pyraleau DB-M d8-64",
        "coords": {
          "x": -2795.53125,
          "y": -430.40625,
          "z": 6056.625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 313,
        "needs_permit": false
      },
      {
        "id64": 2552510729195,
        "name": "Pyraleau RE-F d12-74",
        "coords": {
          "x": -2860.65625,
          "y": -383.6875,
          "z": 6399.15625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 351.8,
        "needs_permit": false
      },
      {
        "id64": 2586803358723,
        "name": "Nyeajaae NC-C d75",
        "coords": {
          "x": -3175.125,
          "y": -371.90625,
          "z": 6619.90625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 384.4,
        "needs_permit": false
      },
      {
        "id64": 112885419043,
        "name": "Nyeajaae CB-V d3-3",
        "coords": {
          "x": -3264.84375,
          "y": -377.5,
          "z": 6964.34375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 356,
        "needs_permit": false
      },
      {
        "id64": 2243138849851,
        "name": "Nyeajaae NO-P d6-65",
        "coords": {
          "x": -3482.21875,
          "y": -462.4375,
          "z": 7190.8125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 325.2,
        "needs_permit": false
      },
      {
        "id64": 1349752097883,
        "name": "Nyeajaae BN-I d10-39",
        "coords": {
          "x": -3631.125,
          "y": -446.59375,
          "z": 7504.5
        },
        "mainStar": "Neutron Star",
        "hop_dist": 347.6,
        "needs_permit": false
      },
      {
        "id64": 2586652331115,
        "name": "Nyeajaae IU-E d12-75",
        "coords": {
          "x": -3902.84375,
          "y": -539.28125,
          "z": 7668.53125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 330.6,
        "needs_permit": false
      },
      {
        "id64": 2998918876291,
        "name": "Flyiedge TX-B d87",
        "coords": {
          "x": -4142.40625,
          "y": -491,
          "z": 7950.21875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 372.9,
        "needs_permit": false
      },
      {
        "id64": 1624495754403,
        "name": "Flyiedge LM-U d3-47",
        "coords": {
          "x": -4247.125,
          "y": -649.75,
          "z": 8290.15625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 389.5,
        "needs_permit": false
      },
      {
        "id64": 284465941691,
        "name": "Flyiedge ZZ-O d6-8",
        "coords": {
          "x": -4264.09375,
          "y": -675.59375,
          "z": 8489.46875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 201.7,
        "needs_permit": false
      },
      {
        "id64": 1212162100443,
        "name": "Flyiedge OY-H d10-35",
        "coords": {
          "x": -4345.9375,
          "y": -729.84375,
          "z": 8803.1875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 328.7,
        "needs_permit": false
      },
      {
        "id64": 2586501319923,
        "name": "Flyiedge VV-C d13-75",
        "coords": {
          "x": -4574.65625,
          "y": -651.875,
          "z": 9063.53125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 355.2,
        "needs_permit": false
      },
      {
        "id64": 1796176989459,
        "name": "Skaude YU-X d1-52",
        "coords": {
          "x": -4803.34375,
          "y": -678.5625,
          "z": 9373.59375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 386.2,
        "needs_permit": false
      },
      {
        "id64": 604380148937,
        "name": "Skaude BL-N b23-0",
        "coords": {
          "x": -4961.75,
          "y": -719.375,
          "z": 9679.65625
        },
        "mainStar": "M (Red dwarf) Star",
        "hop_dist": 347,
        "needs_permit": false
      },
      {
        "id64": 1211977534795,
        "name": "Skaudai NH-L d8-35",
        "coords": {
          "x": -5250.34375,
          "y": -765.28125,
          "z": 9947.25
        },
        "mainStar": "Neutron Star",
        "hop_dist": 396.2,
        "needs_permit": false
      },
      {
        "id64": 43679337835,
        "name": "Skaudai XK-E d12-1",
        "coords": {
          "x": -5516.875,
          "y": -732.9375,
          "z": 10232.5
        },
        "mainStar": "Neutron Star",
        "hop_dist": 391.7,
        "needs_permit": false
      },
      {
        "id64": 284197506443,
        "name": "Prua Phoe BP-Z d8",
        "coords": {
          "x": -5525.25,
          "y": -714.96875,
          "z": 10539.40625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 307.5,
        "needs_permit": false
      },
      {
        "id64": 1521114533291,
        "name": "Prua Phoe PN-S d4-44",
        "coords": {
          "x": -5708,
          "y": -707.78125,
          "z": 10871.6875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 379.3,
        "needs_permit": false
      },
      {
        "id64": 2483136859587,
        "name": "Prua Phoe AB-N d7-72",
        "coords": {
          "x": -5949.03125,
          "y": -748.15625,
          "z": 11148.8125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 369.5,
        "needs_permit": false
      },
      {
        "id64": 3823149895147,
        "name": "Prua Phoe RK-E d12-111",
        "coords": {
          "x": -6042.75,
          "y": -720.125,
          "z": 11523
        },
        "mainStar": "Neutron Star",
        "hop_dist": 386.8,
        "needs_permit": false
      },
      {
        "id64": 1383574916627,
        "name": "Clooku XU-X d1-40",
        "coords": {
          "x": -6155.65625,
          "y": -697.46875,
          "z": 11897.625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 391.9,
        "needs_permit": false
      },
      {
        "id64": 8496023998003,
        "name": "Clooku KY-Q d5-247",
        "coords": {
          "x": -6286.59375,
          "y": -652.6875,
          "z": 12245.53125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 374.4,
        "needs_permit": false
      },
      {
        "id64": 3960521739867,
        "name": "Clooku FY-H d10-115",
        "coords": {
          "x": -6375.03125,
          "y": -701.25,
          "z": 12623.71875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 391.4,
        "needs_permit": false
      },
      {
        "id64": 558874103411,
        "name": "Blua Hypa DW-C d13-16",
        "coords": {
          "x": -6534.90625,
          "y": -630.25,
          "z": 12910.3125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 335.8,
        "needs_permit": false
      },
      {
        "id64": 7327708991131,
        "name": "Stuelou LB-W d2-213",
        "coords": {
          "x": -6685.9375,
          "y": -729.1875,
          "z": 13260.125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 393.7,
        "needs_permit": false
      },
      {
        "id64": 6331243024059,
        "name": "Stuelou ZZ-O d6-184",
        "coords": {
          "x": -6803.625,
          "y": -709.5625,
          "z": 13618.875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 378.1,
        "needs_permit": false
      },
      {
        "id64": 14680659447523,
        "name": "Stuelou TE-G d11-427",
        "coords": {
          "x": -6859.71875,
          "y": -671.40625,
          "z": 14000.21875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 387.3,
        "needs_permit": false
      },
      {
        "id64": 11725671616259,
        "name": "Blua Eaec UI-B d341",
        "coords": {
          "x": -7052.375,
          "y": -710.53125,
          "z": 14334.625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 387.9,
        "needs_permit": false
      },
      {
        "id64": 25538269646627,
        "name": "Blua Eaec LC-U d3-743",
        "coords": {
          "x": -7150.46875,
          "y": -752.53125,
          "z": 14692.1875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 373.1,
        "needs_permit": false
      },
      {
        "id64": 3140738836388,
        "name": "Blua Eaec MN-T e3-731",
        "coords": {
          "x": -7287.0625,
          "y": -784.96875,
          "z": 15026.0625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 362.2,
        "needs_permit": false
      },
      {
        "id64": 18631895158635,
        "name": "Blua Eaec NP-E d12-542",
        "coords": {
          "x": -7443.625,
          "y": -649.25,
          "z": 15360.53125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 393.4,
        "needs_permit": false
      },
      {
        "id64": 10797858017163,
        "name": "Boelts SO-Z d314",
        "coords": {
          "x": -7578.4375,
          "y": -674.6875,
          "z": 15664.15625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 333.2,
        "needs_permit": false
      },
      {
        "id64": 22170881085355,
        "name": "Boeph VN-S d4-645",
        "coords": {
          "x": -7746.84375,
          "y": -683,
          "z": 15981.6875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 359.5,
        "needs_permit": false
      },
      {
        "id64": 22892418813891,
        "name": "Boeph GG-N d7-666",
        "coords": {
          "x": -7864.59375,
          "y": -678.8125,
          "z": 16286.6875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 327,
        "needs_permit": false
      },
      {
        "id64": 16741992091627,
        "name": "Boeph YK-E d12-487",
        "coords": {
          "x": -8031.96875,
          "y": -690.34375,
          "z": 16634.15625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 385.9,
        "needs_permit": false
      },
      {
        "id64": 695960719371,
        "name": "Eoch Flyuae AP-Z d20",
        "coords": {
          "x": -8191.21875,
          "y": -711.40625,
          "z": 16971.8125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 373.9,
        "needs_permit": false
      },
      {
        "id64": 28424219234339,
        "name": "Eoch Flyuae LC-U d3-827",
        "coords": {
          "x": -8389.5,
          "y": -745.53125,
          "z": 17254.40625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 346.9,
        "needs_permit": false
      },
      {
        "id64": 32272493170763,
        "name": "Eoch Flyuae CM-L d8-939",
        "coords": {
          "x": -8542.1875,
          "y": -733.96875,
          "z": 17613.09375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 390,
        "needs_permit": false
      },
      {
        "id64": 108035699478643,
        "name": "Eoch Flyuae XL-C d13-3144",
        "coords": {
          "x": -8620.34375,
          "y": -773.3125,
          "z": 17994.21875
        },
        "mainStar": "Neutron Star",
        "hop_dist": 391,
        "needs_permit": false
      },
      {
        "id64": 21002448638091,
        "name": "Dryio Flyuae VJ-Z d611",
        "coords": {
          "x": -8734.875,
          "y": -800.46875,
          "z": 18269.0625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 299,
        "needs_permit": false
      },
      {
        "id64": 1401239324756,
        "name": "Dryio Flyuae FW-W e1-326",
        "coords": {
          "x": -8858.25,
          "y": -829.46875,
          "z": 18554.375
        },
        "mainStar": "Neutron Star",
        "hop_dist": 312.2,
        "needs_permit": false
      },
      {
        "id64": 22926526861515,
        "name": "Dryooe Flyou PC-L d8-667",
        "coords": {
          "x": -9047.6875,
          "y": -851.25,
          "z": 18897
        },
        "mainStar": "Neutron Star",
        "hop_dist": 392.1,
        "needs_permit": false
      },
      {
        "id64": 9835432988907,
        "name": "Dryooe Flyou DB-E d12-286",
        "coords": {
          "x": -9231.75,
          "y": -887.15625,
          "z": 19223.90625
        },
        "mainStar": "Neutron Star",
        "hop_dist": 376.9,
        "needs_permit": false
      },
      {
        "id64": 37701147250955,
        "name": "Eol Prou FF-Z d1097",
        "coords": {
          "x": -9407.1875,
          "y": -898.96875,
          "z": 19555.8125
        },
        "mainStar": "Neutron Star",
        "hop_dist": 375.6,
        "needs_permit": false
      },
      {
        "id64": 3238296097059,
        "name": "Colonia",
        "coords": {
          "x": -9530.5,
          "y": -910.28125,
          "z": 19808.125
        },
        "mainStar": "F (White) Star",
        "hop_dist": 281.1,
        "needs_permit": false
      }
    ],
    "total": 23344.3,
    "direct": 22000.5,
    "diff_pct": 6.1
  },
  "timestamp": 1779733555412
};

function applyRouteToUI(route, name = null) {
  if (name && name.includes('[Carrier]')) {
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
    applyRouteToUI(route, name);
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

$('load-demo').addEventListener('click', () => {
  applyRouteToUI(DEMO_ROUTE);
  // Auto-open 3D view for "wow" factor
  if ($('visualizer-container').classList.contains('hidden')) {
    $('toggle-3d').click();
  }
  showToast("Demo route loaded!");
});

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
  if (document.fullscreenElement) {
    document.exitFullscreen();
  }
  $('visualizer-container').classList.add('hidden');
  $('toggle-3d').classList.remove('hidden');
});

$('reset-camera').addEventListener('click', () => {
  if (galaxyView) {
    galaxyView.frameRoute(lastResult ? lastResult.path : null);
  }
});

$('toggle-fullscreen').addEventListener('click', () => {
  const container = $('visualizer-container');
  if (!document.fullscreenElement) {
    container.requestFullscreen().catch(err => {
      showToast(`Error attempting to enable full-screen mode: ${err.message}`);
    });
  } else {
    document.exitFullscreen();
  }
});

document.addEventListener('fullscreenchange', () => {
  const container = $('visualizer-container');
  const btn = $('toggle-fullscreen');
  if (document.fullscreenElement === container) {
    container.classList.add('is-fullscreen');
    btn.textContent = 'Exit Fullscreen';
  } else {
    container.classList.remove('is-fullscreen');
    btn.textContent = '⛶ Fullscreen';
  }
  if (galaxyView) {
    // Small delay to ensure container has resized
    setTimeout(() => galaxyView.onResize(), 100);
  }
});
