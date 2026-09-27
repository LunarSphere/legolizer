import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Box, ArrowUpRight, BookOpen, Download, ShoppingBag, RotateCcw, Rotate3D, Move, ChevronRight, X, Layers3, Check, ExternalLink, MousePointerClick, Scan } from 'lucide-react';
import Viewer from './Viewer';
import ARMode, { beginARSession, createAROverlayRoot } from './ARMode';
import BuildLibrary from './BuildLibrary';
import RefinePanel from './RefinePanel';
import { api, assetUrl, buildId, isDemo } from './api';

const noSelection = [];

const initialSettings = { model: true, grid: true, edges: true, autoRotate: false };
const colors = { Blue: '#145da0', Red: '#c33432', Yellow: '#f4ce37', White: '#f5f4ed', Black: '#212121', Green: '#237841', 'Light Gray': '#aaa9a4', 'Dark Gray': '#626560' };
function Toggle({ title, detail, checked, onChange }) {
  return <label className="toggle-row"><span><strong>{title}</strong><small>{detail}</small></span><input type="checkbox" checked={checked} onChange={onChange} /><span className="check-box" aria-hidden="true">{checked && <Check size={13} strokeWidth={3} />}</span></label>;
}
function PartsDialog({ parts, build, onClose }) {
  const dialog = useRef(null);
  useEffect(() => { dialog.current.showModal(); }, []);
  return <dialog ref={dialog} onCancel={onClose} onClick={e => { if (e.target === dialog.current) onClose(); }} className="parts-dialog">
    <header><div><p className="eyebrow">EVERY PIECE, ACCOUNTED FOR</p><h2>Your parts list</h2><p>{build.partCount} pieces · {parts.length} part & color combinations</p></div><button className="icon-button" onClick={onClose} aria-label="Close parts list"><X size={20} /></button></header>
    <div className="table-scroll"><table><thead><tr><th>Part</th><th>Color</th><th>Qty</th><th>Find it</th></tr></thead><tbody>{parts.map(p => <tr key={`${p.part_id}-${p.color_id}`}><td><b>{p.part_id}</b><small>LDraw part</small></td><td><span className="swatch" style={{ background: p.rgb || colors[p.color] || '#aaa' }} />{p.color}</td><td>{p.quantity}</td><td><a href={assetUrl(p.bricklink_url)} target="_blank" rel="noreferrer">BrickLink <ArrowUpRight size={14} /></a></td></tr>)}</tbody></table></div>
    <footer><p>Links open the part catalog. Select the listed color and quantity when purchasing; availability and prices vary.</p><a className="button secondary" href={assetUrl(build.assets.parts)} download><Download size={16} /> Download list</a></footer>
  </dialog>;
}
export default function App() {
  const [selectedId, setSelectedId] = useState(() => {
    try { return isDemo ? buildId : localStorage.getItem('legolizer.selectedBuild') || buildId; }
    catch { return buildId; }
  });
  const [assembly, setAssembly] = useState({ id: null, key: 0 });
  const selectBuild = id => {
    setSelectedId(id); setAssembly(a => ({ id, key: a.key + 1 })); setPartsOpen(false); closeAR(); setSettings(initialSettings);
    setPosition({ x: 0, y: 0, z: 0 }); setResetKey(n => n + 1); clearSelection();
    try { localStorage.setItem('legolizer.selectedBuild', id); } catch {}
  };
  const [selected, setSelected] = useState([]);
  const [libraryKey, setLibraryKey] = useState(0);
  const [refineNotice, setRefineNotice] = useState('');
  const clearSelection = () => setSelected([]);
  const togglePiece = piece => {
    setSelected(current => current.some(p => p.key === piece.key) ? current.filter(p => p.key !== piece.key) : [...current, piece]);
    setRefineNotice('');
  };
  const [attempt, setAttempt] = useState(0);
  const loadKey = `${selectedId}:${attempt}`;
  const [loaded, setLoaded] = useState({ key: null, data: null, error: '' });
  const data = loaded.key === loadKey ? loaded.data : null;
  const error = loaded.key === loadKey ? loaded.error : '';
  const [settings, setSettings] = useState(initialSettings);
  const [mode, setMode] = useState('orbit');
  const [position, setPosition] = useState({ x: 0, y: 0, z: 0 });
  const [resetKey, setResetKey] = useState(0);
  const [partsOpen, setPartsOpen] = useState(false);
  const [arOpen, setArOpen] = useState(false);
  const [arLaunch, setArLaunch] = useState(null);
  const closeAR = useCallback(() => {
    setArLaunch(prev => {
      if (prev?.sessionPromise) {
        prev.sessionPromise.then(session => session.end().catch(() => {})).catch(() => {});
      }
      prev?.overlayRoot?.remove();
      return null;
    });
    setArOpen(false);
  }, [setArLaunch, setArOpen]);
  const openAR = () => {
    if (arOpen) return;
    // requestSession must start in this click turn; do not await support checks first.
    const overlayRoot = createAROverlayRoot();
    const sessionPromise = beginARSession(overlayRoot);
    setArLaunch({ overlayRoot, sessionPromise });
    setArOpen(true);
  };
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.getBuild(selectedId, controller.signal), api.getParts(selectedId, controller.signal)])
      .then(([build, inventory]) => {
        if (build.status !== 'ready') throw new Error('This build is still being prepared. Try again shortly.');
        if (!build.assets?.model || !Array.isArray(inventory.parts)) throw new Error('The server returned an incomplete build.');
        setLoaded({ key: loadKey, data: { build, parts: inventory.parts }, error: '' });
      }).catch(e => { if (e.name !== 'AbortError') setLoaded({ key: loadKey, data: null, error: e.message }); });
    return () => controller.abort();
  }, [loadKey, selectedId]);
  const reset = () => { setPosition({ x: 0, y: 0, z: 0 }); setResetKey(n => n + 1); };
  const toggle = key => setSettings(s => ({ ...s, [key]: !s[key] }));
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/"><span className="brand-icon"><Box size={23} /></span>legolizer<span className="brand-tag">STUDIO</span></a><div className="topbar-right"><span className="local-badge"><i />{isDemo ? 'Local workspace' : 'Connected workspace'}</span><span className="avatar">L</span></div></header>
    <main>
      <div className="breadcrumb">Workspace <ChevronRight size={13} /> <span>{data?.build.name || 'Your build'}</span></div>
      <section className="page-heading"><div><p className="eyebrow">FROM IMAGINATION TO ASSEMBLY</p><h1>Make room for a little wonder.</h1><p>Your idea, piece by piece. Explore it. Build it. Make it yours.</p></div><span className="project-label"><span className="tiny-brick" />{isDemo ? 'DEMO BUILD / 001' : 'YOUR BUILD'}</span></section>
      <BuildLibrary selectedId={selectedId} onSelect={selectBuild} refreshKey={libraryKey} />
      {error ? <div className="load-error" role="alert"><h2>We couldn’t open this build.</h2><p>{error}</p><button className="button primary" onClick={() => setAttempt(n => n + 1)}>Try again</button></div> : !data ? <div className="loading-card" role="status"><span className="spinner" />Opening your workspace…</div> : <>
        <div className="workspace">
          <section className="stage" aria-label="3D model viewer">
            <div className="stage-heading"><span className="stage-label"><span className="status-dot" />LIVE 3D PREVIEW</span><span className="stage-count">{data.build.partCount} pieces of possibility</span></div>
            <Viewer build={data.build} settings={settings} mode={mode} position={position} resetKey={resetKey} paused={arOpen} selected={mode === 'select' ? selected : noSelection} onPick={togglePiece} assembleKey={assembly.id === data.build.id ? assembly.key : 0} />
            <div className="view-toolbar"><div className="tool-group"><button className={mode === 'orbit' ? 'active' : ''} onClick={() => setMode('orbit')} aria-pressed={mode === 'orbit'} title="Rotate view"><Rotate3D size={18} /><span>Orbit</span></button><button className={mode === 'pan' ? 'active' : ''} onClick={() => setMode('pan')} aria-pressed={mode === 'pan'} title="Pan view"><Move size={18} /><span>Pan</span></button>{!isDemo && <button className={mode === 'select' ? 'active' : ''} onClick={() => setMode('select')} aria-pressed={mode === 'select'} title="Select bricks to refine"><MousePointerClick size={18} /><span>Select</span></button>}<button className={arOpen ? 'active' : ''} onClick={openAR} aria-pressed={arOpen} title="View in augmented reality"><Scan size={18} /><span>AR</span></button></div><span className="tool-divider" /><button className="reset-view" onClick={reset} title="Reset view and position"><RotateCcw size={17} /><span>Reset</span></button></div>
            {mode === 'select' && <RefinePanel build={data.build} selected={selected} notice={refineNotice} onClear={clearSelection} onQueued={job => { clearSelection(); setLibraryKey(n => n + 1); setRefineNotice(`${job.name} is queued. It will appear in Saved sets when it’s ready.`); }} />}
            <div className="stage-bottom"><span><span className="mouse-icon" />{mode === 'select' ? <>Click bricks to select<b>·</b>Drag to rotate</> : <>Drag to {mode === 'orbit' ? 'rotate' : 'pan'}</>}<b>·</b>Scroll to zoom<b>·</b>Pinch on touch</span><span>X / Y / Z</span></div>
          </section>
          <aside className="sidebar">
            <div className="build-card"><p className="eyebrow">MEET YOUR NEXT BUILD</p><div className="build-title"><h2>{data.build.name}</h2><span className="ready-badge"><Check size={12} />Ready</span></div><p>{data.build.description}</p>{data.build.brief && <details className="brief"><summary>Expanded prompt</summary><p>{data.build.brief.prompt}</p>{data.build.brief.palette.length > 0 && <small>Palette: {data.build.brief.palette.join(', ')}</small>}</details>}<div className="stats"><div><strong>{data.build.partCount}</strong><span>pieces</span></div><div><strong>{data.build.colorCount}</strong><span>colors</span></div><div><strong>{data.build.stepCount}</strong><span>steps</span></div></div><div className="palette">{[...new Map(data.parts.map(p => [p.color, p.rgb || colors[p.color] || '#aaa'])).entries()].map(([name, rgb]) => <span key={name} title={name} style={{ background: rgb }} />)}<small>Your build’s palette</small></div>
              {data.build.refinement && <p className="refine-note">Refined: “{data.build.refinement.prompt}”. {data.build.refinement.selection?.length ? `Edited ${data.build.refinement.selection.length} selected brick${data.build.refinement.selection.length === 1 ? '' : 's'} and their surroundings; ` : data.build.refinement.region ? 'Edited one region; ' : 'Whole-model edit; '}{data.build.refinement.keptPieces} earlier pieces stayed in place. <button type="button" onClick={() => selectBuild(data.build.refinement.parentId)}>Open the original</button></p>}</div>            <div className="settings-card"><h3><Layers3 size={16} />Make it your view</h3><Toggle title="Show model" detail="Your build, front and center" checked={settings.model} onChange={() => toggle('model')} /><Toggle title="Show grid" detail="A little perspective" checked={settings.grid} onChange={() => toggle('grid')} /><Toggle title="Piece outlines" detail="See where every brick meets" checked={settings.edges} onChange={() => toggle('edges')} /><Toggle title="Auto-rotate" detail="Take it for a spin" checked={settings.autoRotate} onChange={() => toggle('autoRotate')} />
              <details className="position-controls"><summary>Move model <Move size={13} /></summary><p>Position in LDraw units (20 = one stud).</p>{['x', 'y', 'z'].map(axis => <label key={axis}><span>{axis.toUpperCase()}</span><input type="range" aria-label={`Model ${axis.toUpperCase()} position`} min={axis === 'y' ? 0 : -200} max="200" step="10" value={position[axis]} onChange={e => setPosition(p => ({ ...p, [axis]: Number(e.target.value) }))} /><output>{position[axis]}</output></label>)}</details>
            </div>
            <div className="actions"><a className="button primary" href={assetUrl(data.build.assets.instructions)} target="_blank" rel="noreferrer"><BookOpen size={18} />Open build instructions<ArrowUpRight size={17} /></a><button className="button secondary" onClick={() => setPartsOpen(true)}><ShoppingBag size={17} />Find your pieces<ArrowUpRight size={17} /></button><a className="download-link" href={assetUrl(data.build.assets.ldraw)} download><Download size={14} />Download LDraw model <span>.mpd</span></a></div>
          </aside>
        </div>
        <section className="next-step"><span className="next-icon"><BookOpen size={21} /></span><div><h3>From the screen to your shelf.</h3><p>Your guide has {data.build.stepCount} illustrated steps, with the pieces you need along the way.</p></div><a href={assetUrl(data.build.assets.instructions)} target="_blank" rel="noreferrer">Let’s build <ChevronRight size={17} /></a></section>
        {partsOpen && <PartsDialog parts={data.parts} build={data.build} onClose={() => setPartsOpen(false)} />}
        {arOpen && arLaunch && <ARMode build={data.build} onClose={closeAR} sessionPromise={arLaunch.sessionPromise} overlayRoot={arLaunch.overlayRoot} />}
      </>}
    </main><footer className="site-footer"><span>Small bricks. Big possibilities.</span><span>Built with official LDraw geometry <ExternalLink size={11} /></span></footer>
  </div>;
}
