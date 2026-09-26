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

export default function Viewer({ build, settings, mode, position, resetKey, paused = false }) {
  const host = useRef(null);
  const world = useRef(null);
  const [state, setState] = useState({ loading: true, error: '' });
  useEffect(() => {
    let cancelled = false;
    let renderer;
    const element = host.current;
    setState({ loading: true, error: '' });
    try { renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' }); }
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
      runtime.dirty = true;
    };
    const runtime = { paused: false, dirty: true, settling: 0 };
    const markDirty = () => { runtime.dirty = true; runtime.settling = 30; };
    controls.addEventListener('change', markDirty);
    reset();
    world.current = { scene, controls, grid, reset, model: null, runtime, markDirty };
    const resize = () => {
      const { width, height } = element.getBoundingClientRect();
      renderer.setSize(width, height);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
      markDirty();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();
    // Skip draws while AR (or anything) pauses us, and sleep once damping settles.
    renderer.setAnimationLoop(() => {
      if (runtime.paused) return;
      controls.update();
      const active = controls.autoRotate || runtime.dirty || runtime.settling > 0;
      if (!active) return;
      renderer.render(scene, camera);
      runtime.dirty = false;
      if (runtime.settling > 0) runtime.settling -= 1;
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
      const holder = new THREE.Group();
      holder.add(model);
      scene.add(holder);
      world.current.model = holder;
      markDirty();
      setState({ loading: false, error: '' });
    })().catch(error => {
      if (!cancelled) setState({ loading: false, error: `Unable to load the model. ${error.message || 'Reload to try again.'}` });
    });
    return () => {
      cancelled = true;
      observer.disconnect();
      controls.removeEventListener('change', markDirty);
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
    w.runtime.paused = paused;
    if (!paused) w.markDirty();
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
      w.model.traverse(child => { if (child.isLineSegments) child.visible = settings.edges; });
    }
    w.markDirty();
  }, [settings, position, mode, state.loading, paused]);
  useEffect(() => { world.current?.reset(); }, [resetKey]);
  return <div className={`viewer-canvas ${mode}`} ref={host}>
    {state.loading && <div className="viewer-message" role="status"><span className="spinner" />Assembling your view…</div>}
    {state.error && <div className="viewer-message error" role="alert">{state.error}<a href={assetUrl(build.assets.preview)} target="_blank" rel="noreferrer">View the rendered image ↗</a></div>}
    {!settings.model && !state.loading && !state.error && <div className="viewer-message">Model hidden · enable “Show model” to bring it back</div>}
  </div>;
}
