import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
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

export default function Viewer({ build, settings, mode, position, resetKey, selected = [], onPick }) {
  const host = useRef(null);
  const world = useRef(null);
  const pick = useRef(null);
  pick.current = mode === 'select' ? onPick : null;
  const [state, setState] = useState({ loading: true, error: '' });
  useEffect(() => {
    let cancelled = false;
    let renderer;
    const element = host.current;
    setState({ loading: true, error: '' });
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true }); }
    catch { setState({ loading: false, error: '3D needs WebGL. Enable hardware acceleration or try another browser.' }); return; }
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
    controls.maxDistance = 2200;
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
    const reset = () => {
      camera.position.set(420, 330, 550);
      controls.target.set(0, 105, 0);
      controls.update();
    };
    reset();
    world.current = { scene, controls, grid, reset, model: null, ldraw: null, overlay: null };
    const raycaster = new THREE.Raycaster();
    let pressed = null;
    const onPointerDown = event => { pressed = event.button === 0 ? [event.clientX, event.clientY] : null; };
    const onPointerUp = event => {
      const w = world.current;
      if (!pressed || !pick.current || !w?.ldraw || !w.model.visible) return;
      const moved = Math.hypot(event.clientX - pressed[0], event.clientY - pressed[1]);
      pressed = null;
      if (moved > 5) return;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
      const hit = raycaster.intersectObjects(w.ldraw.children, true).find(h => h.object.isMesh);
      if (!hit) return;
      let piece = hit.object;
      while (piece.parent !== w.ldraw) piece = piece.parent;
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
    renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
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
      const holder = new THREE.Group();
      holder.add(model);
      const overlay = new THREE.Group();
      overlay.position.copy(model.position);
      overlay.rotation.copy(model.rotation);
      holder.add(overlay);
      scene.add(holder);
      Object.assign(world.current, { model: holder, ldraw: model, overlay });
      setState({ loading: false, error: '' });
    })().catch(error => {
      if (!cancelled) setState({ loading: false, error: `Unable to load the model. ${error.message || 'Reload to try again.'}` });
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
    if (!w) return;
    w.grid.visible = settings.grid;
    w.controls.autoRotate = settings.autoRotate && settings.model;
    w.controls.mouseButtons.LEFT = mode === 'pan' ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
    w.controls.touches.ONE = mode === 'pan' ? THREE.TOUCH.PAN : THREE.TOUCH.ROTATE;
    if (w.model) {
      w.model.visible = settings.model;
      w.model.position.set(position.x, position.y, position.z);
      w.ldraw.traverse(child => { if (child.isLineSegments) child.visible = settings.edges; });
    }
  }, [settings, position, mode, state.loading]);
  useEffect(() => {
    const overlay = world.current?.overlay;
    if (!overlay) return;
    const outline = new THREE.LineBasicMaterial({ color: 0xff00c8, depthTest: false, transparent: true });
    const fill = new THREE.MeshBasicMaterial({ color: 0xff00c8, transparent: true, opacity: 0.25, depthWrite: false });
    for (const piece of selected) overlay.add(cellBox(piece, fill, 1.5), cellBox(piece, outline, 1));
    return () => { disposeModel(overlay); overlay.clear(); };
  }, [selected, state.loading]);
  useEffect(() => { world.current?.reset(); }, [resetKey]);
  return <div className={`viewer-canvas ${mode}`} ref={host}>
    {state.loading && <div className="viewer-message" role="status"><span className="spinner" />Assembling your view…</div>}
    {state.error && <div className="viewer-message error" role="alert">{state.error}<a href={assetUrl(build.assets.preview)} target="_blank" rel="noreferrer">View the rendered image ↗</a></div>}
    {!settings.model && !state.loading && !state.error && <div className="viewer-message">Model hidden · enable “Show model” to bring it back</div>}
  </div>;
}
