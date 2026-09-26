import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as THREE from 'three';
import { LDrawLoader } from 'three/addons/loaders/LDrawLoader.js';
import { LDrawConditionalLineMaterial } from 'three/addons/materials/LDrawConditionalLineMaterial.js';
import { X, Rotate3D, Move, Scan } from 'lucide-react';
import { assetUrl } from './api';

function disposeObject(object) {
  const geometries = new Set();
  const materials = new Set();
  object.traverse(child => {
    if (child.geometry) geometries.add(child.geometry);
    if (child.material) (Array.isArray(child.material) ? child.material : [child.material]).forEach(m => materials.add(m));
  });
  geometries.forEach(g => g.dispose());
  materials.forEach(m => m.dispose());
}

export async function checkARSupport() {
  if (typeof navigator === 'undefined' || !navigator.xr || !navigator.xr.isSessionSupported) {
    return { ok: false, reason: 'This browser does not expose WebXR. Open Studio on a phone with Chrome (Android) or another browser that supports immersive AR.' };
  }
  try {
    const ok = await navigator.xr.isSessionSupported('immersive-ar');
    if (!ok) {
      return { ok: false, reason: 'Immersive AR is not available here. Use a supported phone browser over HTTPS (or localhost), and allow camera access when prompted.' };
    }
    return { ok: true, reason: '' };
  } catch {
    return { ok: false, reason: 'Could not check AR support. Try again on a supported mobile browser.' };
  }
}

/** Call synchronously from a click handler so requestSession keeps user activation. */
export function beginARSession(overlayRoot) {
  if (typeof navigator === 'undefined' || !navigator.xr?.requestSession) {
    return Promise.reject(new Error('This browser does not expose WebXR. Open Studio on a phone with Chrome (Android) or another browser that supports immersive AR.'));
  }
  return navigator.xr.requestSession('immersive-ar', {
    requiredFeatures: ['hit-test'],
    optionalFeatures: ['dom-overlay', 'light-estimation'],
    domOverlay: { root: overlayRoot },
  });
}

export function createAROverlayRoot() {
  const root = document.createElement('div');
  root.className = 'ar-overlay ar-overlay-fixed';
  document.body.appendChild(root);
  return root;
}

function makeReticle() {
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.08, 0.1, 32).rotateX(-Math.PI / 2),
    new THREE.MeshBasicMaterial({ color: 0xf8e9a9 }),
  );
  ring.matrixAutoUpdate = false;
  ring.visible = false;
  return ring;
}

export default function ARMode({ build, onClose, sessionPromise, overlayRoot }) {
  const host = useRef(null);
  const touchLayer = useRef(null);
  const [support, setSupport] = useState(() => (
    sessionPromise
      ? { checking: false, ok: true, reason: '' }
      : { checking: true, ok: false, reason: '' }
  ));
  const [status, setStatus] = useState(sessionPromise ? 'Starting camera…' : 'Checking AR…');
  const [placed, setPlaced] = useState(false);
  const [gesture, setGesture] = useState('rotate');
  const gestureRef = useRef('rotate');
  const placedRef = useRef(false);

  useEffect(() => {
    gestureRef.current = gesture;
  }, [gesture]);

  useEffect(() => {
    placedRef.current = placed;
  }, [placed]);

  useEffect(() => {
    if (sessionPromise) return undefined;
    let cancelled = false;
    checkARSupport().then(result => {
      if (!cancelled) setSupport({ checking: false, ...result });
    });
    return () => { cancelled = true; };
  }, [sessionPromise]);

  useEffect(() => {
    if (!sessionPromise) return undefined;

    let cancelled = false;
    let renderer;
    let session = null;
    let hitTestSource = null;
    let hitTestSourceRequested = false;
    const element = host.current;
    const surface = touchLayer.current;
    if (!element || !surface) {
      setSupport({ checking: false, ok: false, reason: 'AR overlay failed to initialize.' });
      return undefined;
    }

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera();
    const reticle = makeReticle();
    scene.add(reticle);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x777b86, 1.4));
    const key = new THREE.DirectionalLight(0xffffff, 1.8);
    key.position.set(-1, 2, 1);
    scene.add(key);

    const modelRoot = new THREE.Group();
    modelRoot.visible = false;
    scene.add(modelRoot);

    const state = {
      yaw: 0,
      offset: new THREE.Vector3(),
      scale: 1,
      baseScale: 1,
      pointers: new Map(),
      pinchStart: 0,
      scaleStart: 1,
      lastX: 0,
      lastY: 0,
    };

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    } catch {
      setSupport({ checking: false, ok: false, reason: 'WebGL is required for AR.' });
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.xr.enabled = true;
    renderer.xr.setReferenceSpaceType('local');
    element.appendChild(renderer.domElement);
    renderer.domElement.className = 'ar-canvas';

    const applyTransform = () => {
      modelRoot.rotation.set(0, state.yaw, 0);
      modelRoot.scale.setScalar(state.baseScale * state.scale);
      if (modelRoot.userData.anchor) {
        // Pan in the horizontal plane relative to the model's yaw.
        const cos = Math.cos(state.yaw);
        const sin = Math.sin(state.yaw);
        const local = state.offset;
        modelRoot.position.set(
          modelRoot.userData.anchor.x + local.x * cos + local.z * sin,
          modelRoot.userData.anchor.y,
          modelRoot.userData.anchor.z - local.x * sin + local.z * cos,
        );
      }
    };

    const placeAt = matrix => {
      const position = new THREE.Vector3().setFromMatrixPosition(matrix);
      modelRoot.userData.anchor = position.clone();
      state.offset.set(0, 0, 0);
      placedRef.current = true;
      modelRoot.visible = true;
      reticle.visible = false;
      setPlaced(true);
      setStatus('Placed · drag to move');
      applyTransform();
    };

    const onSelect = () => {
      if (!reticle.visible || placedRef.current) return;
      placeAt(reticle.matrix);
    };

    const controller = renderer.xr.getController(0);
    controller.addEventListener('select', onSelect);
    scene.add(controller);

    const distance = (a, b) => Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);

    // WebXR DOM overlays receive touches; the WebGL canvas usually does not.
    const onPointerDown = event => {
      if (event.target?.closest?.('button, a, input, .ar-gestures, .ar-top, .ar-banner')) return;
      event.preventDefault();
      state.pointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      if (state.pointers.size === 2) {
        const [a, b] = [...state.pointers.values()];
        state.pinchStart = distance(a, b);
        state.scaleStart = state.scale;
      }
      try { surface.setPointerCapture(event.pointerId); } catch { /* older WebViews */ }
    };
    const onPointerMove = event => {
      if (!state.pointers.has(event.pointerId)) return;
      event.preventDefault();
      state.pointers.set(event.pointerId, { clientX: event.clientX, clientY: event.clientY });
      if (!placedRef.current) return;

      if (state.pointers.size === 2) {
        const [a, b] = [...state.pointers.values()];
        const d = distance(a, b);
        if (state.pinchStart > 0) {
          state.scale = Math.min(4, Math.max(0.25, state.scaleStart * (d / state.pinchStart)));
          applyTransform();
        }
        return;
      }

      const dx = event.clientX - state.lastX;
      const dy = event.clientY - state.lastY;
      state.lastX = event.clientX;
      state.lastY = event.clientY;
      if (dx === 0 && dy === 0) return;

      const mode = gestureRef.current;
      if (mode === 'rotate') {
        state.yaw += dx * 0.012;
      } else if (mode === 'pan') {
        state.offset.x += dx * 0.0012;
        state.offset.z += dy * 0.0012;
      }
      applyTransform();
    };
    const onPointerUp = event => {
      if (!state.pointers.has(event.pointerId)) return;
      state.pointers.delete(event.pointerId);
      if (state.pointers.size < 2) state.pinchStart = 0;
      try { surface.releasePointerCapture(event.pointerId); } catch { /* ignore */ }
    };

    surface.addEventListener('pointerdown', onPointerDown, { passive: false });
    surface.addEventListener('pointermove', onPointerMove, { passive: false });
    surface.addEventListener('pointerup', onPointerUp);
    surface.addEventListener('pointercancel', onPointerUp);
    surface.addEventListener('lostpointercapture', onPointerUp);

    const loader = new LDrawLoader();
    loader.setConditionalLineMaterial(LDrawConditionalLineMaterial);

    (async () => {
      // Session was requested in the AR button click; await it before loading.
      setStatus('Starting camera…');
      session = await sessionPromise;
      if (cancelled) return;
      session.addEventListener('end', () => {
        session = null;
        if (!cancelled) onClose();
      });
      await renderer.xr.setSession(session);
      if (cancelled) return;

      setStatus('Loading model…');
      // Local packed MPD + LDConfig only — never a remote parts library.
      await loader.preloadMaterials(assetUrl(build.assets.colors));
      if (cancelled) return;
      const model = await loader.loadAsync(assetUrl(build.assets.model));
      if (cancelled) { disposeObject(model); return; }
      model.rotation.x = Math.PI;
      model.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      model.position.set(-center.x, -box.min.y, -center.z);
      // Fit to roughly 12 cm on the table in XR meters.
      const longest = Math.max(size.x, size.y, size.z) || 1;
      state.baseScale = 0.12 / longest;
      modelRoot.add(model);
      applyTransform();
      setStatus('Point at a table · tap to place');

      renderer.setAnimationLoop((timestamp, frame) => {
        if (!frame || cancelled) return;
        const refSpace = renderer.xr.getReferenceSpace();
        const xrSession = renderer.xr.getSession();

        if (hitTestSourceRequested === false) {
          xrSession.requestReferenceSpace('viewer').then(viewerSpace => {
            xrSession.requestHitTestSource({ space: viewerSpace }).then(source => {
              hitTestSource = source;
            }).catch(() => {
              setStatus('Hit-testing unavailable. Try another surface or browser.');
            });
          });
          xrSession.addEventListener('end', () => {
            hitTestSourceRequested = false;
            hitTestSource = null;
          });
          hitTestSourceRequested = true;
        }

        if (hitTestSource && !placedRef.current) {
          const hits = frame.getHitTestResults(hitTestSource);
          if (hits.length) {
            const pose = hits[0].getPose(refSpace);
            if (pose) {
              reticle.visible = true;
              reticle.matrix.fromArray(pose.transform.matrix);
            }
          } else {
            reticle.visible = false;
          }
        }

        renderer.render(scene, camera);
      });
    })().catch(error => {
      if (cancelled) return;
      const reason = error?.message || 'Could not start AR. Close and try again on a supported phone.';
      setStatus(reason);
      setSupport({ checking: false, ok: false, reason });
    });

    return () => {
      cancelled = true;
      renderer?.setAnimationLoop(null);
      surface.removeEventListener('pointerdown', onPointerDown);
      surface.removeEventListener('pointermove', onPointerMove);
      surface.removeEventListener('pointerup', onPointerUp);
      surface.removeEventListener('pointercancel', onPointerUp);
      surface.removeEventListener('lostpointercapture', onPointerUp);
      if (hitTestSource) {
        hitTestSource.cancel?.();
        hitTestSource = null;
      }
      // Do not end the XR session or remove the overlay here: both are owned by
      // the click-started launch in App so React StrictMode remounts keep them.
      disposeObject(scene);
      if (renderer) {
        renderer.dispose();
        renderer.domElement.remove();
      }
    };
  }, [sessionPromise, overlayRoot, build, onClose]);

  const overlay = (
    <>
      <div
        className={`ar-touch-layer${placed ? ' is-active' : ''}`}
        ref={touchLayer}
        aria-hidden="true"
      />
      <header className="ar-top">
        <p className="eyebrow">AR PREVIEW</p>
        <button type="button" className="icon-button ar-close" onClick={onClose} aria-label="Close AR">
          <X size={20} />
        </button>
      </header>
      {support.checking && <div className="ar-banner" role="status"><span className="spinner" />Checking AR support…</div>}
      {!support.checking && !support.ok && (
        <div className="ar-fallback" role="alert">
          <Scan size={28} />
          <h2>AR isn’t available here</h2>
          <p>{support.reason}</p>
          <p className="ar-fallback-hint">Studio orbit, generate, and parts tools keep working when you close this panel.</p>
          <button type="button" className="button primary" onClick={onClose}>Back to studio</button>
        </div>
      )}
      {support.ok && (
        <>
          <div className="ar-banner" role="status">{status}</div>
          {placed && (
            <div className="ar-gestures" role="toolbar" aria-label="Model gestures">
              <button type="button" className={gesture === 'rotate' ? 'active' : ''} aria-pressed={gesture === 'rotate'} onClick={() => setGesture('rotate')}><Rotate3D size={16} />Rotate</button>
              <button type="button" className={gesture === 'pan' ? 'active' : ''} aria-pressed={gesture === 'pan'} onClick={() => setGesture('pan')}><Move size={16} />Pan</button>
            </div>
          )}
          <p className="ar-hint">{placed ? 'Drag on the screen · pinch to scale' : 'Move until the ring sits on the table, then tap'}</p>
        </>
      )}
    </>
  );

  return (
    <div className="ar-shell" role="dialog" aria-modal="true" aria-label="Augmented reality preview">
      <div className="ar-host" ref={host} />
      {overlayRoot ? createPortal(overlay, overlayRoot) : <div className="ar-overlay">{overlay}</div>}
    </div>
  );
}
