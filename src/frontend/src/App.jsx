import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUpRight, Download, RotateCcw, Rotate3D, Move, X, Check, MousePointerClick, BoxSelect, Scan } from 'lucide-react';
import Viewer from './Viewer';
import ARMode, { beginARSession, createAROverlayRoot } from './ARMode';
import BuildLibrary from './BuildLibrary';
import RefinePanel from './RefinePanel';
import AccountMenu, { forgetGoogleSelection } from './AccountMenu';
import { api, assetUrl, buildId, demoBuildId, isDemo, noSession } from './api';

const noSelection = [];
function sharedBuildId() {
  const id = new URLSearchParams(window.location.search).get('build');
  return id && /^[\w-]+$/.test(id) ? id : null;
}
function forgetSharedLink() {
  if (sharedBuildId()) window.history.replaceState(null, '', window.location.pathname);
}

const initialSettings = { grid: true, edges: true, autoRotate: false };
const colors = { Blue: '#145da0', Red: '#c33432', Yellow: '#f4ce37', White: '#f5f4ed', Black: '#212121', Green: '#237841', 'Light Gray': '#aaa9a4', 'Dark Gray': '#626560' };
function Toggle({ title, detail, checked, onChange }) {
  return <label className="toggle-row"><span><strong>{title}</strong>{detail && <small>{detail}</small>}</span><input type="checkbox" checked={checked} onChange={onChange} /><span className="check-box" aria-hidden="true">{checked && <Check size={13} strokeWidth={3} />}</span></label>;
}
function BuildName({ id, name, canRename, onRenamed }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const renameButton = useRef(null);
  const wasEditing = useRef(false);
  useEffect(() => {
    if (!editing && wasEditing.current) renameButton.current?.focus();
    wasEditing.current = editing;
  }, [editing]);
  const start = () => { setDraft(name); setError(''); setEditing(true); };
  const cancel = () => { if (!saving) setEditing(false); };
  const save = async e => {
    e.preventDefault();
    const next = draft.trim();
    if (!next) { setError('it needs a name; anything up to 80 characters works.'); return; }
    if (next === name) { setEditing(false); return; }
    setSaving(true); setError('');
    try { const build = await api.renameBuild(id, next); onRenamed(build.name); setEditing(false); }
    catch (err) { setError(err.message); }
    finally { setSaving(false); }
  };
  if (!editing) return <div className="build-title"><h2>{name}</h2>{canRename && <button ref={renameButton} type="button" className="text-button" onClick={start}>rename</button>}</div>;
  return <form className="rename-form" onSubmit={save} onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); cancel(); } }}>
    <label htmlFor="build-name" className="visually-hidden">set name</label>
    <input id="build-name" value={draft} onChange={e => setDraft(e.target.value)} maxLength={80} disabled={saving} autoFocus />
    <div><button type="submit" className="button primary" disabled={saving}>{saving ? 'saving…' : 'save'}</button><button type="button" className="button secondary" disabled={saving} onClick={cancel}>cancel</button></div>
    {error && <p className="form-error" role="alert">{error}</p>}
  </form>;
}
function PartsDialog({ parts, build, onClose }) {
  const dialog = useRef(null);
  useEffect(() => { dialog.current.showModal(); }, []);
  return <dialog ref={dialog} onCancel={onClose} onClick={e => { if (e.target === dialog.current) onClose(); }} className="parts-dialog">
    <header><div><h2>parts list</h2><p>{build.partCount} pieces across {parts.length} part-and-color combinations; the bricklink links open in a new tab.</p></div><button className="icon-button" onClick={onClose} aria-label="close parts list"><X size={20} /></button></header>
    <div className="table-scroll"><table><thead><tr><th>part</th><th>color</th><th>qty</th><th>find it</th></tr></thead><tbody>{parts.map(p => <tr key={`${p.part_id}-${p.color_id}`}><td><b>{p.part_id}</b><small>ldraw part</small></td><td><span className="swatch" style={{ background: p.rgb || colors[p.color] || '#aaa' }} />{p.color}</td><td>{p.quantity}</td><td><a href={assetUrl(p.bricklink_url)} target="_blank" rel="noreferrer">bricklink <ArrowUpRight size={14} /></a></td></tr>)}</tbody></table></div>
    <footer><p>pick the listed color and quantity when you order; stock and prices vary from seller to seller.</p><a className="button secondary" href={assetUrl(build.assets.parts)} download><Download size={16} />download the list</a></footer>
  </dialog>;
}
export default function App() {
  const [selectedId, setSelectedId] = useState(() => {
    if (isDemo) return buildId;
    let remembered = null;
    try { remembered = localStorage.getItem('legolizer.selectedBuild'); } catch {}
    return sharedBuildId() || (remembered !== demoBuildId && remembered) || buildId || null;
  });
  const [assembly, setAssembly] = useState({ id: null, key: 0 });
  const selectBuild = id => {
    setSelectedId(id); setAssembly(a => ({ id, key: a.key + 1 })); setPartsOpen(false); closeAR(); setSettings(initialSettings);
    setPosition({ x: 0, y: 0, z: 0 }); setResetKey(n => n + 1); clearSelection(); setShareNote(''); forgetSharedLink();
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
  const setRegionSelection = pieces => {
    setSelected(pieces);
    setRefineNotice('');
  };
  const [session, setSession] = useState(null);
  const [accountError, setAccountError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api.getSession(controller.signal).then(setSession).catch(e => { if (e.name !== 'AbortError') setSession(noSession); });
    return () => controller.abort();
  }, []);
  const signIn = async credential => {
    setAccountError('');
    try { setSession(await api.signIn(credential)); setLibraryKey(n => n + 1); }
    catch (e) { setAccountError(e.message); }
  };
  const signOut = async () => {
    setAccountError('');
    try {
      setSession(await api.signOut());
      forgetGoogleSelection();
      clearSelection(); setMode('orbit'); setLibraryKey(n => n + 1); setAttempt(n => n + 1);
    } catch (e) { setAccountError(e.message); }
  };
  const [attempt, setAttempt] = useState(0);
  const loadKey = `${selectedId}:${attempt}`;
  const [loaded, setLoaded] = useState({ key: null, data: null, error: '' });
  const data = loaded.key === loadKey ? loaded.data : null;
  const paused = !!session?.paused;
  const canRename = !isDemo && !!session?.user && data?.build.mine !== false;
  const canEdit = canRename && !paused;
  const [nameOverride, setNameOverride] = useState(null);
  const buildName = data && nameOverride?.id === data.build.id ? nameOverride.name : data?.build.name;
  const renamed = name => { setNameOverride({ id: data.build.id, name }); setLibraryKey(n => n + 1); };
  const [pausing, setPausing] = useState(false);
  const refreshSession = () => api.getSession().then(setSession).catch(() => {});
  const togglePause = async () => {
    setPausing(true); setAccountError('');
    try { const state = await api.setPaused(!paused); setSession(current => ({ ...current, paused: state.paused })); }
    catch (e) { setAccountError(e.message); }
    finally { setPausing(false); }
  };
  const [shareOverride, setShareOverride] = useState(null);
  const [shareBusy, setShareBusy] = useState(false);
  const [shareNote, setShareNote] = useState('');
  const shared = data && shareOverride?.id === data.build.id ? shareOverride : data?.build;
  const isPublic = shared?.visibility === 'public';
  const toggleShare = async () => {
    const id = data.build.id;
    setShareBusy(true); setShareNote('');
    try {
      const build = await api.setVisibility(id, isPublic ? 'private' : 'public');
      setShareOverride({ id, visibility: build.visibility, authorName: build.authorName });
      setLibraryKey(n => n + 1);
    } catch (e) { setShareNote(e.message); }
    finally { setShareBusy(false); }
  };
  const copyLink = async () => {
    const url = `${window.location.origin}/?build=${encodeURIComponent(data.build.id)}`;
    try { await navigator.clipboard.writeText(url); setShareNote('link copied.'); }
    catch { setShareNote(`copy this link: ${url}`); }
  };
  const error = loaded.key === loadKey ? loaded.error : '';
  const [settings, setSettings] = useState(initialSettings);
  const [mode, setMode] = useState('orbit');
  const [selectTool, setSelectTool] = useState('click');
  const beginSelect = tool => { setMode('select'); setSelectTool(tool); };
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
  const [nothingToOpen, setNothingToOpen] = useState(null);
  useEffect(() => {
    if (selectedId || !session) return undefined;
    const controller = new AbortController();
    const signal = controller.signal;
    const mine = session.user || session.auth !== 'google' ? api.listBuilds(signal).then(page => page.items, () => []) : Promise.resolve([]);
    mine.then(items => items.length ? items : api.listGallery('', signal).then(page => page.items))
      .then(items => { if (items[0]) setSelectedId(items[0].id); else setNothingToOpen(session); })
      .catch(e => { if (e.name !== 'AbortError') setNothingToOpen(session); });
    return () => controller.abort();
  }, [selectedId, session]);
  useEffect(() => {
    if (!selectedId) return undefined;
    const controller = new AbortController();
    Promise.all([api.getBuild(selectedId, controller.signal), api.getParts(selectedId, controller.signal)])
      .then(([build, inventory]) => {
        if (build.status !== 'ready') throw new Error('this set is still being put together; try again in a minute.');
        if (!build.assets?.model || !Array.isArray(inventory.parts)) throw new Error('the server sent back an incomplete set.');
        setLoaded({ key: loadKey, data: { build, parts: inventory.parts }, error: '' });
      }).catch(e => {
        if (e.name === 'AbortError') return;
        if (e.status === 404 && selectedId !== buildId) {
          setSelectedId(buildId || null);
          forgetSharedLink();
          try { localStorage.removeItem('legolizer.selectedBuild'); } catch {}
          return;
        }
        setLoaded({ key: loadKey, data: null, error: e.message });
      });
    return () => controller.abort();
  }, [loadKey, selectedId]);
  const reset = () => { setPosition({ x: 0, y: 0, z: 0 }); setResetKey(n => n + 1); };
  const toggle = key => setSettings(s => ({ ...s, [key]: !s[key] }));
  const [navRequest, setNavRequest] = useState({ target: null, key: 0 });
  const navigate = target => e => { e.preventDefault(); setNavRequest(r => ({ target, key: r.key + 1 })); };
  const workspace = error ? <div className="load-error" role="alert"><h2>couldn’t open this set</h2><p>{error}</p><button className="button primary" onClick={() => setAttempt(n => n + 1)}>try again</button></div> : !data ? <div className="loading-card" role="status">{!selectedId && nothingToOpen && nothingToOpen === session ? 'no sets yet; describe something above and it’ll turn up here.' : <><span className="spinner" />opening the set…</>}</div> : <>
        <div className="workspace">
          <section className="stage" aria-label="3d model viewer">
            <Viewer build={data.build} settings={settings} mode={mode} selectTool={selectTool} position={position} resetKey={resetKey} paused={arOpen} selected={mode === 'select' ? selected : noSelection} onPick={togglePiece} onRegion={setRegionSelection} assembleKey={assembly.id === data.build.id ? assembly.key : 0} />
            <div className="view-toolbar"><div className="tool-group"><button className={mode === 'orbit' ? 'active' : ''} onClick={() => setMode('orbit')} aria-pressed={mode === 'orbit'} title="turn the view"><Rotate3D size={18} /><span>orbit</span></button><button className={mode === 'pan' ? 'active' : ''} onClick={() => setMode('pan')} aria-pressed={mode === 'pan'} title="slide the view"><Move size={18} /><span>pan</span></button>{canEdit && <><button className={mode === 'select' && selectTool === 'click' ? 'active' : ''} onClick={() => beginSelect('click')} aria-pressed={mode === 'select' && selectTool === 'click'} title="pick bricks to refine"><MousePointerClick size={18} /><span>select</span></button><button className={mode === 'select' && selectTool === 'region' ? 'active' : ''} onClick={() => beginSelect('region')} aria-pressed={mode === 'select' && selectTool === 'region'} title="pick a region between two bricks"><BoxSelect size={18} /><span>region</span></button></>}<button className={arOpen ? 'active' : ''} onClick={openAR} aria-pressed={arOpen} title="view it in augmented reality"><Scan size={18} /><span>ar</span></button></div><span className="tool-divider" /><button className="reset-view" onClick={reset} title="reset the view and position"><RotateCcw size={17} /><span>reset</span></button></div>
            {mode === 'select' && canEdit && <RefinePanel build={data.build} buildName={buildName} selected={selected} notice={refineNotice} onClear={clearSelection} onQueued={job => { clearSelection(); setLibraryKey(n => n + 1); setRefineNotice(`${job.name} is in the queue; it’ll turn up in my sets when it’s done.`); }} />}
            <p className="stage-hint">{mode === 'select' ? selectTool === 'region' ? 'click two bricks for opposite corners; drag to turn it.' : 'click bricks to pick them; drag to turn it.' : mode === 'orbit' ? 'drag to turn it; scroll or pinch to get closer.' : 'drag to slide it around; scroll or pinch to get closer.'}</p>
          </section>
          <aside className="sidebar">
            <div className="build-card"><BuildName key={data.build.id} id={data.build.id} name={buildName} canRename={canRename} onRenamed={renamed} /><p className="build-description">{data.build.description}</p>{data.build.brief && <details className="brief"><summary>expanded prompt</summary><p>{data.build.brief.prompt}</p>{data.build.brief.palette.length > 0 && <small>palette: {data.build.brief.palette.join(', ')}</small>}{data.build.brief.reference && <small>reference photo: {data.build.brief.reference.page ? <a href={data.build.brief.reference.page} target="_blank" rel="noreferrer">{data.build.brief.reference.title}</a> : data.build.brief.reference.title}{data.build.brief.reference.artist && ` by ${data.build.brief.reference.artist}`}{data.build.brief.reference.license && `, ${data.build.brief.reference.license}`} (Wikimedia Commons)</small>}</details>}
              <div className="build-actions"><a className="button primary" href={assetUrl(data.build.assets.instructions)} target="_blank" rel="noreferrer">build instructions (pdf)<ArrowUpRight size={18} /></a><button type="button" className="button secondary" onClick={() => setPartsOpen(true)}>parts list</button><a className="button secondary" href={assetUrl(data.build.assets.ldraw)} download>download (.mpd)<Download size={18} /></a></div>
              <div className="stats"><div><strong>{data.build.partCount}</strong><span>pieces</span></div><div><strong>{data.build.colorCount}</strong><span>colors</span></div><div><strong>{data.build.stepCount}</strong><span>steps</span></div></div><div className="palette"><small>colors</small>{[...new Map(data.parts.map(p => [p.color, p.rgb || colors[p.color] || '#aaa'])).entries()].map(([name, rgb]) => <span key={name} title={name} style={{ background: rgb }} />)}</div>
              {data.build.refinement && <p className="refine-note">refined with “{data.build.refinement.prompt}”; {data.build.refinement.selection?.length ? `we reworked ${data.build.refinement.selection.length} selected brick${data.build.refinement.selection.length === 1 ? '' : 's'} and what’s around them, and ` : data.build.refinement.region ? 'we reworked one region, and ' : 'we reworked the whole model, and '}{data.build.refinement.keptPieces} earlier pieces stayed put. {data.build.mine !== false && <button type="button" onClick={() => selectBuild(data.build.refinement.parentId)}>open the original</button>}</p>}
              {!isDemo && (data.build.mine || isPublic) && <div className="share-panel">
                <div>{data.build.mine ? <button type="button" className="button secondary" disabled={shareBusy} onClick={toggleShare}>{isPublic ? 'take it out of the gallery' : 'publish to the gallery'}</button> : <small>shared by {shared.authorName || 'a builder'}</small>}
                  {isPublic && <button type="button" className="text-button" onClick={copyLink}>copy link</button>}</div>
                <small role="status">{shareNote || (data.build.mine ? isPublic ? `in the gallery as ${shared.authorName}; anyone with the link can open it.` : 'publishing shows its name, description, 3d model, parts list and instructions to everyone.' : '')}</small>
              </div>}</div>
            <div className="settings-card"><h3>view</h3><Toggle title="piece outlines" detail="draws a line where one brick meets the next" checked={settings.edges} onChange={() => toggle('edges')} /><Toggle title="auto-rotate" detail="turns it slowly while you look" checked={settings.autoRotate} onChange={() => toggle('autoRotate')} />
              <details className="position-controls"><summary>move model</summary><p>position in ldraw units; 20 is one stud.</p>{['x', 'y', 'z'].map(axis => <label key={axis}><span>{axis}</span><input type="range" aria-label={`model ${axis} position`} min={axis === 'y' ? 0 : -200} max="200" step="10" value={position[axis]} onChange={e => setPosition(p => ({ ...p, [axis]: Number(e.target.value) }))} /><output>{position[axis]}</output></label>)}</details>
            </div>
          </aside>
        </div>
        {partsOpen && <PartsDialog parts={data.parts} build={data.build} onClose={() => setPartsOpen(false)} />}
        {arOpen && arLaunch && <ARMode build={data.build} onClose={closeAR} sessionPromise={arLaunch.sessionPromise} overlayRoot={arLaunch.overlayRoot} />}
      </>;
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/">legolizer</a><nav className="primary-nav" aria-label="main">{!isDemo && <a href="#new-build" onClick={navigate('new')}>new build</a>}<a href="#library" onClick={navigate('mine')}>my sets</a><a href="#library" onClick={navigate('gallery')}>gallery</a></nav><div className="topbar-right"><AccountMenu session={session} onSignIn={signIn} onSignOut={signOut} /></div></header>
    <main>
      {(paused || (session?.admin && !isDemo)) && <div className={`pause-banner ${paused ? '' : 'running'}`} role="status">
        <p>{paused ? 'generation is paused for now to save compute; your sets are all still here.' : 'generation is on.'}</p>
        {session?.admin && !isDemo && <button type="button" className="button secondary" disabled={pausing} onClick={togglePause}>{paused ? 'resume generation' : 'pause generation'}</button>}
      </div>}
      {accountError && <p className="form-error account-error" role="alert">{accountError}</p>}
      <BuildLibrary selectedId={selectedId} onSelect={selectBuild} refreshKey={libraryKey} session={session} onPaused={refreshSession} workspace={workspace} navRequest={navRequest} />
    </main><footer className="site-footer"><p>made from official ldraw parts. lego is a trademark of the lego group, which has nothing to do with this site.</p></footer>
  </div>;
}
