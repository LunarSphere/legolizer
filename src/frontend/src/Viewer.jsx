import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { Pause, Play } from 'lucide-react';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { LDrawLoader } from 'three/addons/loaders/LDrawLoader.js';
import { LDrawConditionalLineMaterial } from 'three/addons/materials/LDrawConditionalLineMaterial.js';
import { assetUrl } from './api';

function disposeModel(object) {
  const geometries = new Set();
  const materials = new Set();
  object.traverse(child => {
    if (child.geometry) geometries.add(child.geometry);
    if (child.material) (Array.isArray(child.material) ? child.material : [child.material]).forEach(m => materials.add(m));
  });
  geometries.forEach(g => g.dispose());
  materials.forEach(m => m.dispose());
}

const STUD = 20;
const PLATE = 8;
const STUD_HEIGHT = 4;

// Grid cells (x/y in studs, z in plates; inclusive) of one placed piece, from its LDraw-space bounds.
function pieceCells(piece, ldraw) {
  const box = new THREE.Box3().setFromObject(piece).applyMatrix4(ldraw.matrixWorld.clone().invert());
  return {
    min: [Math.round(box.min.x / STUD), Math.round(box.min.z / STUD), Math.round(-box.max.y / PLATE)],
    max: [Math.round(box.max.x / STUD) - 1, Math.round(box.max.z / STUD) - 1, Math.round((-box.min.y - STUD_HEIGHT) / PLATE) - 1],
  };
}

function cellBox({ min, max }, material, pad = 0) {
  const size = [(max[0] - min[0] + 1) * STUD + pad, (max[2] - min[2] + 1) * PLATE + pad, (max[1] - min[1] + 1) * STUD + pad];
  const geometry = new THREE.BoxGeometry(...size);
  const object = material.isLineBasicMaterial ? new THREE.LineSegments(new THREE.EdgesGeometry(geometry), material) : new THREE.Mesh(geometry, material);
  if (material.isLineBasicMaterial) geometry.dispose();
  object.position.set((min[0] + max[0] + 1) * STUD / 2, -(min[2] + max[2] + 1) * PLATE / 2, (min[1] + max[1] + 1) * STUD / 2);
  object.renderOrder = 10;
  return object;
}

const HOME_CAMERA = new THREE.Vector3(420, 330, 550);
const HOME_TARGET = new THREE.Vector3(0, 105, 0);
const HOME_DIRECTION = HOME_CAMERA.clone().sub(HOME_TARGET).normalize();
const HOME_DISTANCE = HOME_CAMERA.distanceTo(HOME_TARGET);
const MAX_DISTANCE = 2200;
const FIT_PADDING = 1.12;
// Pixels covered by the stage heading (top) and the toolbar + hint row (bottom); the model is framed between them.
const VIEW_INSETS = { top: 56, bottom: 130 };

// Target and distance along HOME_DIRECTION at which every corner of `box` fits the unobstructed band of the
// view, centered in that band. Never closer than the default distance, so small builds keep the familiar framing.
function frameBox(camera, box, viewHeight) {
  if (!box) return { target: HOME_TARGET, distance: HOME_DISTANCE };
  const target = box.getCenter(new THREE.Vector3());
  const forward = HOME_DIRECTION.clone().negate();
  const right = new THREE.Vector3().crossVectors(forward, camera.up).normalize();
  const up = new THREE.Vector3().crossVectors(right, forward);
  const top = Math.min(VIEW_INSETS.top / viewHeight, 0.2);
  const bottom = Math.min(VIEW_INSETS.bottom / viewHeight, 0.3);
  const tanFull = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
  const tanV = tanFull * (1 - top - bottom) / FIT_PADDING;
  const tanH = tanFull * camera.aspect / FIT_PADDING;
  const corner = new THREE.Vector3();
  let distance = HOME_DISTANCE;
  for (let i = 0; i < 8; i++) {
    corner.set(i & 1 ? box.max.x : box.min.x, i & 2 ? box.max.y : box.min.y, i & 4 ? box.max.z : box.min.z).sub(target);
    const towardCamera = corner.dot(HOME_DIRECTION);
    distance = Math.max(distance, towardCamera + Math.abs(corner.dot(up)) / tanV, towardCamera + Math.abs(corner.dot(right)) / tanH);
  }
  target.addScaledVector(up, -(bottom - top) * tanFull * distance);
  return { target, distance };
}
const ASSEMBLY_MS = 2500;
const DROP_MS = 380;
const DROP_HEIGHT = 800;
const MIN_DROP_MS = 120;
const MAX_DROP = 3000;
// Brick height plus studs, so a spawned brick starts fully above the view edge.
const SPAWN_MARGIN = 30;
const FRAME_LAG_MS = 100;

const viewProjection = new THREE.Matrix4();
const clipPoint = new THREE.Vector4();
const clipUp = new THREE.Vector4();

// World-space rise from `point` until it crosses the top edge of the camera's view.
function riseToViewTop(camera, point) {
  camera.updateMatrixWorld();
  viewProjection.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
  clipPoint.set(point.x, point.y, point.z, 1).applyMatrix4(viewProjection);
  clipUp.set(0, 1, 0, 0).applyMatrix4(viewProjection);
  const closing = clipUp.y - clipUp.w;
  if (clipPoint.w <= 0 || closing <= 1e-6) return DROP_HEIGHT;
  return Math.min(Math.max((clipPoint.w - clipPoint.y) / closing, 0) + SPAWN_MARGIN, MAX_DROP);
}

// Layers are MPD steps (one per voxel layer); within a layer, pieces drop far corner first from the
// home camera. The per-piece gap makes a full 0 → top run last ASSEMBLY_MS. The model is flipped about X,
// so world z = -LDraw z and world up = LDraw -y. Each drop starts at the top edge of the current view,
// and its duration scales with sqrt(distance) like a free fall.
function createAssembly(ldraw, camera) {
  const landed = new THREE.Vector3();
  const startFall = p => {
    ldraw.updateWorldMatrix(true, false);
    landed.set(p.piece.position.x, p.y, p.piece.position.z).applyMatrix4(ldraw.matrixWorld);
    p.drop = riseToViewTop(camera, landed);
    p.duration = Math.max(DROP_MS * Math.sqrt(p.drop / DROP_HEIGHT), MIN_DROP_MS);
    p.piece.visible = true;
  };
  const stepOf = piece => piece.userData.buildingStep ?? 0;
  const nearness = piece => HOME_CAMERA.x * piece.position.x - HOME_CAMERA.z * piece.position.z;
  const steps = [...new Set(ldraw.children.map(stepOf))].sort((a, b) => a - b);
  const pieces = ldraw.children
    .map(piece => ({ piece, y: piece.position.y, layer: steps.indexOf(stepOf(piece)), near: nearness(piece), shown: true, at: 0 }))
    .sort((a, b) => a.layer - b.layer || a.near - b.near);
  const gap = (ASSEMBLY_MS - DROP_MS) / Math.max(pieces.length - 1, 1);
  const falling = new Set();
  let lastTick = null;
  return {
    layers: steps.length,
    get busy() { return falling.size > 0; },
    show(layer, now, animate) {
      let queueEnd = -Infinity;
      for (const p of falling) queueEnd = Math.max(queueEnd, p.at);
      for (const p of pieces) {
        const shown = p.layer < layer;
        if (shown === p.shown) continue;
        p.shown = shown;
        p.piece.position.y = p.y;
        if (shown && animate) {
          p.at = queueEnd = Math.max(now, queueEnd + gap);
          p.piece.visible = false;
          falling.add(p);
        } else {
          falling.delete(p);
          p.piece.visible = shown;
        }
      }
    },
    // Returns the highest layer with a piece in the air, so auto-play can move the slider thumb.
    tick(now) {
      const lag = lastTick === null ? 0 : now - lastTick - FRAME_LAG_MS;
      lastTick = now;
      let started = 0;
      for (const p of falling) {
        if (lag > 0) p.at += lag;
        if (now < p.at) continue;
        if (!p.piece.visible) startFall(p);
        const t = Math.min((now - p.at) / p.duration, 1);
        p.piece.position.y = p.y - p.drop * (1 - t * t);
        started = Math.max(started, p.layer + 1);
        if (t === 1) falling.delete(p);
      }
      return started;
    },
  };
}

const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export default function Viewer({ build, settings, mode, position, resetKey, paused = false, selected = [], onPick, assembleKey = 0 }) {
  const host = useRef(null);
  const world = useRef(null);
  const pick = useRef(null);
  const assembled = useRef(0);
  const assembleRequest = useRef(assembleKey);
  useLayoutEffect(() => {
    pick.current = mode === 'select' ? onPick : null;
    assembleRequest.current = assembleKey;
  });
  const [loaded, setLoaded] = useState({ build: null, error: '' });
  const state = { loading: loaded.build !== build, error: loaded.build === build ? loaded.error : '' };
  const [layers, setLayers] = useState(0);
  const [layer, setLayer] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    let cancelled = false;
    let renderer;
    const element = host.current;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    // eslint-disable-next-line react-hooks/set-state-in-effect -- terminal WebGL failure; the effect exits without further updates
    catch { setLoaded({ build, error: '3D needs WebGL. Enable hardware acceleration or try another browser.' }); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    element.appendChild(renderer.domElement);
    renderer.domElement.setAttribute('aria-label', 'Interactive robot model. Drag to orbit, right-drag to pan, scroll to zoom.');
    renderer.domElement.setAttribute('role', 'img');
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(35, 1, 1, 10000);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 130;
    controls.maxDistance = MAX_DISTANCE;
    controls.maxPolarAngle = Math.PI * 0.85;
    controls.autoRotateSpeed = 1;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x777b86, 2.8));
    const key = new THREE.DirectionalLight(0xffffff, 3);
    key.position.set(-250, 500, 450);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 1.2);
    fill.position.set(300, 100, -300);
    scene.add(fill);
    const grid = new THREE.GridHelper(800, 40, 0xc4c9c3, 0xe0e3dd);
    grid.position.y = -1;
    scene.add(grid);
    const runtime = { paused: false };
    let bounds = null;
    const reset = () => {
      const { target, distance } = frameBox(camera, bounds, Math.max(element.clientHeight, 1));
      controls.maxDistance = Math.max(MAX_DISTANCE, distance * 1.5);
      controls.target.copy(target);
      camera.position.copy(target).addScaledVector(HOME_DIRECTION, distance);
      controls.update();
    };
    reset();
    world.current = { scene, controls, grid, reset, model: null, ldraw: null, overlay: null, runtime };
    const raycaster = new THREE.Raycaster();
    let pressed = null;
    let assembly = null;
    let autoplay = null;
    const onPointerDown = event => { pressed = event.button === 0 ? [event.clientX, event.clientY] : null; };
    const onPointerUp = event => {
      const w = world.current;
      if (!pressed || !pick.current || !w?.ldraw || !w.model.visible || assembly?.busy) return;
      const moved = Math.hypot(event.clientX - pressed[0], event.clientY - pressed[1]);
      pressed = null;
      if (moved > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
      const pieceOf = object => { while (object.parent !== w.ldraw) object = object.parent; return object; };
      const piece = raycaster.intersectObjects(w.ldraw.children, true).filter(h => h.object.isMesh).map(h => pieceOf(h.object)).find(p => p.visible);
      if (!piece) return;
      pick.current({ key: w.ldraw.children.indexOf(piece), ...pieceCells(piece, w.ldraw) });
    };
    renderer.domElement.addEventListener('pointerdown', onPointerDown);
    renderer.domElement.addEventListener('pointerup', onPointerUp);
    const resize = () => {
      const { width, height } = element.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    renderer.setAnimationLoop(time => {
      if (runtime.paused) return;
      const started = assembly?.tick(time) ?? 0;
      if (autoplay) {
        const done = !assembly.busy;
        const thumb = done ? assembly.layers : Math.max(autoplay.thumb, started);
        if (thumb !== autoplay.thumb) setLayer(autoplay.thumb = thumb);
        if (done) { autoplay = null; setPlaying(false); }
      }
      controls.update();
      renderer.render(scene, camera);
    });
    const loader = new LDrawLoader();
    loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);
    // The REST contract requires a packed MPD: no remote parts-library requests.
    (async () => {
      await loader.preloadMaterials(assetUrl(build.assets.colors));
      if (cancelled) return;
      const model = await loader.loadAsync(assetUrl(build.assets.model));
      if (cancelled) { disposeModel(model); return; }
      model.rotation.x = Math.PI;
      model.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(model);
      const center = box.getCenter(new THREE.Vector3());
      model.position.set(-center.x, -box.min.y, -center.z);
      const size = box.getSize(new THREE.Vector3());
      bounds = new THREE.Box3(new THREE.Vector3(-size.x / 2, 0, -size.z / 2), new THREE.Vector3(size.x / 2, size.y, size.z / 2));
      reset();
      const holder = new THREE.Group();
      holder.add(model);
      const overlay = new THREE.Group();
      overlay.position.copy(model.position);
      overlay.rotation.copy(model.rotation);
      holder.add(overlay);
      assembly = createAssembly(model, camera);
      const showLayer = value => {
        autoplay = null;
        setPlaying(false);
        setLayer(value);
        assembly.show(value, performance.now(), !reducedMotion());
      };
      const play = (from = 0) => {
        if (reducedMotion()) { showLayer(assembly.layers); return; }
        const now = performance.now();
        assembly.show(from, now, false);
        assembly.show(assembly.layers, now, true);
        autoplay = { thumb: from };
        setLayer(from);
        setPlaying(true);
      };
      const pause = () => showLayer(autoplay?.thumb ?? assembly.layers);
      Object.assign(world.current, { model: holder, ldraw: model, overlay, play, pause, showLayer });
      setLayers(assembly.layers);
      setLayer(assembly.layers);
      if (assembleRequest.current && assembleRequest.current !== assembled.current) {
        assembled.current = assembleRequest.current;
        play();
      }
      scene.add(holder);
      setLoaded({ build, error: '' });
    })().catch(error => {
      if (!cancelled) setLoaded({ build, error: `Unable to load the model. ${error.message || 'Reload to try again.'}` });
    });
    return () => {
      cancelled = true;
      renderer.domElement.removeEventListener('pointerdown', onPointerDown);
      renderer.domElement.removeEventListener('pointerup', onPointerUp);
      observer.disconnect();
      renderer.setAnimationLoop(null);
      controls.dispose();
      disposeModel(scene);
      renderer.dispose();
      renderer.domElement.remove();
      world.current = null;
    };
  }, [build]);
  useEffect(() => {
    const w = world.current;
    if (!w?.runtime) return;
    w.runtime.paused = paused;
  }, [paused]);
  useEffect(() => {
    const w = world.current;
    if (!w) return;
    w.grid.visible = settings.grid;
    w.controls.autoRotate = settings.autoRotate && settings.model && !paused;
    w.controls.mouseButtons.LEFT = mode === 'pan' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    w.controls.touches.ONE = mode === 'pan' ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
    if (w.model) {
      w.model.visible = settings.model;
      w.model.position.set(position.x, position.y, position.z);
      w.ldraw.traverse(child => { if (child.isLineSegments) child.visible = settings.edges; });
    }
  }, [settings, position, mode, state.loading, paused]);
  useEffect(() => {
    const overlay = world.current?.overlay;
    if (!overlay) return;
    const outline = new THREE.LineBasicMaterial({ color: 0xff00c8, depthTest: false, transparent: true });
    const fill = new THREE.MeshBasicMaterial({ color: 0xff00c8, transparent: true, opacity: 0.25, depthWrite: false });
    for (const piece of selected) overlay.add(cellBox(piece, fill, 1.5), cellBox(piece, outline, 1));
    return () => { disposeModel(overlay); overlay.clear(); };
  }, [selected, state.loading]);
  useEffect(() => { world.current?.reset(); }, [resetKey]);
  useEffect(() => {
    const play = world.current?.play;
    if (!assembleKey || assembleKey === assembled.current || !play) return;
    assembled.current = assembleKey;
    play();
  }, [assembleKey, state.loading]);
  const changeLayer = event => world.current?.showLayer(Number(event.target.value));
  const togglePlay = () => playing ? world.current?.pause() : world.current?.play(layer >= layers ? 0 : layer);
  return <div className={`viewer-canvas ${mode}`} ref={host}>
    {layers > 1 && !state.loading && !state.error && settings.model && <div className="layer-slider">
      <span>Layer</span>
      <output>{layer}<small>/{layers}</small></output>
      <input type="range" min="0" max={layers} step="1" value={layer} onChange={changeLayer} aria-label="Visible build layers" aria-valuetext={`Layer ${layer} of ${layers}`} />
      <button type="button" onClick={togglePlay} aria-label={playing ? 'Pause assembly' : 'Play assembly'} title={playing ? 'Pause' : layer >= layers ? 'Replay the build' : 'Finish the build'}>{playing ? <Pause size={14} /> : <Play size={14} />}</button>
    </div>}
    {state.loading && <div className="viewer-message" role="status"><span className="spinner" />Assembling your view…</div>}
    {state.error && <div className="viewer-message error" role="alert">{state.error}<a href={assetUrl(build.assets.preview)} target="_blank" rel="noreferrer">View the rendered image ↗</a></div>}
    {!settings.model && !state.loading && !state.error && <div className="viewer-message">Model hidden · enable “Show model” to bring it back</div>}
  </div>;
}
