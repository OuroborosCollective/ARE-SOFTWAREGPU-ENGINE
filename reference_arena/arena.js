import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const specs = [
  {alias:'mage', label:'Magier', clip:'Charged_Spell_Cast', x:-1.3, z:-0.8, yaw:0.45},
  {alias:'assassin', label:'Assassinin', clip:'Dodge_and_Counter', x:1.3, z:-0.8, yaw:-0.45},
  {alias:'axe', label:'Axtkämpfer', clip:'Axe_Spin_Attack', x:-1.3, z:1.25, yaw:0.45},
  {alias:'sword', label:'Schwertkämpfer', clip:'Sword_Judgment', x:1.3, z:1.25, yaw:-0.45},
  {alias:'log', label:'Baumstamm', x:-2.7, z:2.75, yaw:0.4, static:true},
  {alias:'boulder', label:'Granitfelsen', x:2.7, z:2.65, yaw:-0.2, static:true},
];
const root = document.querySelector('#view');
const state = document.querySelector('#load-state');
const characterList = document.querySelector('#characters');
const help = document.querySelector('#asset-help');
const renderer = new THREE.WebGLRenderer({antialias:true, alpha:false, powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.08;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
root.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#101820');
scene.fog = new THREE.Fog('#101820', 15, 33);
const camera = new THREE.PerspectiveCamera(43, innerWidth/innerHeight, 0.1, 80);
camera.position.set(8.6, 6.9, 10.8);
const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 1.05, 0.65);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 5;
controls.maxDistance = 22;
controls.maxPolarAngle = Math.PI*0.48;

scene.add(new THREE.HemisphereLight(0xb9d7ef, 0x29221f, 2.05));
const key = new THREE.DirectionalLight(0xfff0d9, 3.1);
key.position.set(-5, 10, 5);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.left = -8; key.shadow.camera.right = 8;
key.shadow.camera.top = 9; key.shadow.camera.bottom = -8;
key.shadow.normalBias = 0.035;
scene.add(key);
const rim = new THREE.DirectionalLight(0x6d9cc9, 1.15);
rim.position.set(4, 6, -7);
scene.add(rim);
const fill = new THREE.PointLight(0x78b7bf, 18, 12, 2);
fill.position.set(0, 3.5, 0.8);
scene.add(fill);

const floor = new THREE.Mesh(new THREE.CircleGeometry(7.2, 96), new THREE.MeshStandardMaterial({
  color:'#28313a', roughness:0.88, metalness:0.08,
}));
floor.rotation.x = -Math.PI/2;
floor.position.y = -0.035;
floor.receiveShadow = true;
scene.add(floor);
const grid = new THREE.GridHelper(14, 28, '#647887', '#43515c');
grid.position.y = -0.018;
grid.material.transparent = true;
grid.material.opacity = 0.27;
scene.add(grid);
const centerDisc = new THREE.Mesh(new THREE.CircleGeometry(3.45, 96), new THREE.MeshStandardMaterial({
  color:'#182129', roughness:0.8, metalness:0.16, side:THREE.DoubleSide,
}));
centerDisc.rotation.x = -Math.PI/2;
centerDisc.position.y = -0.012;
scene.add(centerDisc);
const ring = new THREE.Mesh(new THREE.TorusGeometry(3.35, 0.018, 8, 128), new THREE.MeshStandardMaterial({
  color:'#80c2ca', emissive:'#28515a', emissiveIntensity:0.75, metalness:0.4, roughness:0.45,
}));
ring.rotation.x = Math.PI/2;
ring.position.y = 0.012;
scene.add(ring);

const loader = new GLTFLoader();
const clock = new THREE.Clock();
const actors = new Map();
let paused = false;
let frameCount = 0;
let lastFpsRead = performance.now();
let loadingDone = 0;
let totalTriangles = 0;

function addClipPicker(spec, gltf, mixer) {
  if (spec.static || !gltf.animations.length) return;
  const row = document.createElement('div');
  row.className = 'character';
  const label = document.createElement('label');
  label.textContent = spec.label;
  label.htmlFor = `clip-${spec.alias}`;
  const select = document.createElement('select');
  select.id = `clip-${spec.alias}`;
  select.setAttribute('aria-label', `${spec.label}: Animation auswählen`);
  for (const clip of gltf.animations) {
    const option = document.createElement('option');
    option.value = clip.name;
    option.textContent = clip.name;
    select.appendChild(option);
  }
  const initial = gltf.animations.find(clip => clip.name === spec.clip) || gltf.animations[0];
  select.value = initial.name;
  const actions = new Map(gltf.animations.map(clip => [clip.name, mixer.clipAction(clip)]));
  actions.get(initial.name).play();
  select.addEventListener('change', () => {
    mixer.stopAllAction();
    const next = actions.get(select.value);
    next.reset().fadeIn(0.18).play();
  });
  row.append(label, select);
  characterList.appendChild(row);
}

async function loadSpec(spec) {
  const gltf = await loader.loadAsync(`./assets/${spec.alias}.glb`);
  const object = gltf.scene;
  object.rotation.y = spec.yaw;
  object.updateMatrixWorld(true);
  const originalBounds = new THREE.Box3().setFromObject(object);
  const originalSize = originalBounds.getSize(new THREE.Vector3());
  const longest = Math.max(originalSize.x, originalSize.y, originalSize.z, 1e-5);
  object.scale.multiplyScalar((spec.static ? 1.6 : 1.7)/longest);
  object.updateMatrixWorld(true);
  const scaledBounds = new THREE.Box3().setFromObject(object);
  const center = scaledBounds.getCenter(new THREE.Vector3());
  object.position.x += spec.x-center.x;
  object.position.z += spec.z-center.z;
  object.position.y += -scaledBounds.min.y;
  object.traverse(node => {
    if (!node.isMesh) return;
    node.castShadow = true;
    node.receiveShadow = true;
    if (node.geometry?.index) totalTriangles += node.geometry.index.count/3;
    else if (node.geometry?.attributes?.position) totalTriangles += node.geometry.attributes.position.count/3;
  });
  scene.add(object);
  const mixer = gltf.animations.length ? new THREE.AnimationMixer(object) : null;
  if (mixer) addClipPicker(spec, gltf, mixer);
  actors.set(spec.alias, {mixer, object, clips:gltf.animations.map(clip => clip.name)});
}

async function initialize() {
  const results = await Promise.allSettled(specs.map(loadSpec));
  const failures = results.map((result, i) => result.status === 'rejected' ? `${specs[i].alias}: ${result.reason?.message || result.reason}` : null).filter(Boolean);
  if (failures.length) {
    state.textContent = `${specs.length-failures.length}/${specs.length} Modelle geladen`;
    state.style.color = '#e4b77b';
    help.hidden = false;
    console.error('Reference arena GLB load errors:', failures);
  } else {
    state.textContent = '6/6 GLB-Modelle geladen';
  }
  document.querySelector('#triangles').textContent = `${Math.round(totalTriangles).toLocaleString('de-DE')} Dreiecke`;
  document.querySelector('#play-toggle').disabled = ![...actors.values()].some(actor => actor.mixer);
}

const playToggle = document.querySelector('#play-toggle');
playToggle.addEventListener('click', () => {
  paused = !paused;
  playToggle.textContent = paused ? 'Animation abspielen' : 'Animation pausieren';
  clock.getDelta();
});
document.querySelector('#dismiss-help').addEventListener('click', () => { help.hidden = true; });

function resize() {
  camera.aspect = innerWidth/innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
}
addEventListener('resize', resize);

renderer.setAnimationLoop(() => {
  const delta = Math.min(clock.getDelta(), 0.05);
  if (!paused) for (const actor of actors.values()) actor.mixer?.update(delta);
  controls.update();
  renderer.render(scene, camera);
  frameCount++;
  const now = performance.now();
  if (now-lastFpsRead >= 700) {
    const fps = Math.round(frameCount*1000/(now-lastFpsRead));
    document.querySelector('#fps').textContent = `${fps} FPS`;
    frameCount = 0;
    lastFpsRead = now;
  }
});
initialize().catch(error => {
  state.textContent = 'Arena konnte nicht geladen werden';
  console.error(error);
  help.hidden = false;
});
