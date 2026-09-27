import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { api, assetUrl, isDemo } from './api';
import AssemblyIndicator from './AssemblyIndicator';
const stageLabels = { queued: 'waiting in line', views: 'sketching the idea', scene: 'planning the shape',
  assembly: 'fitting the bricks', render: 'rendering', instructions: 'writing the build guide', complete: 'saved to my sets', failed: 'stopped' };
const ACCEPT_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const scrollBehavior = () => (window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth');
function cameraFailureMessage(error) {
  if (error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError') {
    return 'camera permission was denied; allow camera access when asked (or in your browser settings), or upload a photo instead.';
  }
  if (error?.name === 'NotFoundError' || error?.name === 'DevicesNotFoundError') {
    return 'there’s no camera on this device; upload a photo instead.';
  }
  if (error?.name === 'NotReadableError' || error?.name === 'TrackStartError') {
    return 'another app is using the camera; close it and try again, or upload a photo instead.';
  }
  if (error?.name === 'SecurityError') {
    return 'the camera only works on a secure page (https or localhost); upload a photo instead.';
  }
  return 'couldn’t open the camera; upload a photo instead.';
}

export default function BuildLibrary({ selectedId, onSelect, refreshKey = 0, session, onPaused, workspace, navRequest }) {
  const paused = !!session?.paused;
  const failed = error => { setSubmitError(error.message); if (error.code === 'generation_paused') onPaused?.(); };
  const signedOut = session?.auth === 'google' && !session.user;
  const libraryOpen = !!session && !signedOut;
  const [loadedBuilds, setBuilds] = useState([]);
  const [loadedJobs, setJobs] = useState([]);
  const builds = libraryOpen ? loadedBuilds : [];
  const jobs = libraryOpen ? loadedJobs : [];
  const [mode, setMode] = useState('text');
  const [upload, setUpload] = useState(null);
  const [reading, setReading] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraError, setCameraError] = useState('');
  const fileInput = useRef(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const readVersion = useRef(0);
  const newBuildRef = useRef(null);
  const promptRef = useRef(null);
  const workspaceRef = useRef(null);
  const libraryRef = useRef(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [maxSize, setMaxSize] = useState(null);
  const [stylize, setStylize] = useState(true);
  const [sending, setSending] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [view, setView] = useState(null);
  const [reveal, setReveal] = useState(0);
  const [handledNav, setHandledNav] = useState(navRequest?.key ?? 0);
  if (navRequest && navRequest.key !== handledNav) {
    setHandledNav(navRequest.key);
    if (navRequest.target === 'mine' || navRequest.target === 'gallery') setView(navRequest.target);
  }
  useEffect(() => {
    if (!navRequest?.key) return;
    if (navRequest.target === 'new') {
      newBuildRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
      promptRef.current?.focus({ preventScroll: true });
    } else libraryRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
  }, [navRequest]);
  useEffect(() => {
    if (reveal) workspaceRef.current?.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
  }, [reveal]);
  const pick = id => { onSelect(id); setReveal(n => n + 1); };
  const shown = view ?? (signedOut ? 'gallery' : 'mine');
  const [gallery, setGallery] = useState({ key: null, items: [], next: null, error: '' });
  const [loadingMore, setLoadingMore] = useState(false);
  const galleryReady = gallery.key === refreshKey;
  useEffect(() => {
    if (shown !== 'gallery' || galleryReady) return undefined;
    const controller = new AbortController();
    api.listGallery('', controller.signal)
      .then(page => setGallery({ key: refreshKey, items: page.items, next: page.nextCursor, error: '' }))
      .catch(error => { if (error.name !== 'AbortError') setGallery({ key: refreshKey, items: [], next: null, error: error.message }); });
    return () => controller.abort();
  }, [shown, refreshKey, galleryReady]);
  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api.listGallery(gallery.next);
      setGallery(current => ({ ...current, items: [...current.items, ...page.items.filter(build => !current.items.some(item => item.id === build.id))], next: page.nextCursor }));
    } catch (error) { setGallery(current => ({ ...current, error: error.message })); }
    finally { setLoadingMore(false); }
  }
  const submission = useRef(null);
  const latestJobs = useRef(new Map());
  const openBuild = useRef(onSelect);
  useLayoutEffect(() => { openBuild.current = onSelect; });
  useEffect(() => {
    if (!libraryOpen) return undefined;
    const controller = new AbortController();
    let timer;
    const loadBuilds = async () => {
      const library = await api.listBuilds(controller.signal);
      if (!controller.signal.aborted) setBuilds(library.items);
    };
    const poll = async first => {
      try {
        const [progress] = await Promise.all([api.getJobs(controller.signal), first && loadBuilds()]);
        if (controller.signal.aborted) return;
        setJobs(progress.items);
        setLoadError('');
        let finished = false;
        for (const job of progress.items) {
          const previous = latestJobs.current.get(job.id);
          if (job.status === 'succeeded' && previous && previous !== 'succeeded') {
            finished = true;
            setNotice(`${job.name} is done; it’s in my sets now.`);
            if (job.buildId) { openBuild.current(job.buildId); setReveal(n => n + 1); }
          }
          if (job.status === 'failed' && previous && previous !== 'failed') {
            setNotice(`${job.name} stopped; the details are below, and your saved sets are untouched.`);
          }
          latestJobs.current.set(job.id, job.status);
        }
        if (finished) await loadBuilds();
      } catch (error) {
        if (error.name !== 'AbortError') setLoadError(error.message);
      } finally {
        if (!controller.signal.aborted && !isDemo) timer = setTimeout(() => poll(false), 4000);
      }
    };
    poll(true);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh, refreshKey, libraryOpen]);
  useEffect(() => {
    if (!cameraOpen) return undefined;
    let cancelled = false;
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) {
          throw Object.assign(new Error('unsupported'), { name: 'NotSupportedError' });
        }
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: 'environment' } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }
        streamRef.current = stream;
        const video = videoRef.current;
        if (video) {
          video.srcObject = stream;
          await video.play();
        }
        if (!cancelled) setCameraReady(true);
      } catch (error) {
        if (!cancelled) setCameraError(cameraFailureMessage(error));
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach(track => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [cameraOpen]);
  async function ingestFile(file, inputEl) {
    const version = ++readVersion.current;
    setUpload(null); setSubmitError(''); setReading(false);
    if (!file) return;
    if (!ACCEPT_TYPES.includes(file.type) || file.size > 3 * 1024 * 1024 || !file.size) {
      setSubmitError('that one won’t work; pick a png, jpeg or webp image up to 3 mb.');
      if (inputEl) inputEl.value = '';
      return;
    }
    setReading(true);
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('couldn’t read this image.'));
        reader.readAsDataURL(file);
      });
      const image = new Image();
      image.src = dataUrl;
      await image.decode();
      if (Math.max(image.width, image.height) > 4096 || Math.min(image.width, image.height) < 32) {
        throw new Error('each side of the image has to be between 32 and 4096 pixels.');
      }
      if (version === readVersion.current) setUpload({ name: file.name, dataUrl, mediaType: file.type, data: dataUrl.split(',')[1] });
    } catch (error) { if (version === readVersion.current) setSubmitError(error.message || 'couldn’t open this image.'); }
    finally { if (version === readVersion.current) setReading(false); }
  }
  function chooseImage(event) {
    ingestFile(event.target.files?.[0], event.target);
  }
  function removeImage() {
    readVersion.current++; setReading(false); setUpload(null);
    if (fileInput.current) fileInput.current.value = '';
  }
  function closeCamera() {
    setCameraOpen(false);
    setCameraReady(false);
    setCameraError('');
  }
  function openCamera() {
    if (sending || reading || isDemo) return;
    setSubmitError('');
    setCameraReady(false);
    setCameraError('');
    setCameraOpen(true);
  }
  async function capturePhoto() {
    const video = videoRef.current;
    if (!video?.videoWidth || !cameraReady) return;
    try {
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('couldn’t capture this frame.');
      context.drawImage(video, 0, 0);
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(result => (result ? resolve(result) : reject(new Error('couldn’t capture this frame.'))), 'image/jpeg', 0.92);
      });
      const file = new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
      closeCamera();
      await ingestFile(file);
    } catch (error) {
      setCameraError(error.message || 'couldn’t capture this frame.');
    }
  }
  async function submit(event) {
    event.preventDefault();
    if (sending || reading || (mode === 'text' ? !description.trim() : !upload)) return;
    const body = { description: description.trim(), ...(name.trim() ? { name: name.trim() } : {}),
      ...(maxSize != null ? { maxSize } : {}),
      ...(mode === 'image' ? { image: { mediaType: upload.mediaType, data: upload.data } } : { stylize }) };
    const fingerprint = JSON.stringify(body);
    if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, key: crypto.randomUUID() };
    setSending(true); setSubmitError(''); setNotice('');
    try {
      const job = await api.createBuild(body, submission.current.key);
      submission.current = null;
      setDescription(''); setName(''); setMaxSize(null); removeImage();
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
      latestJobs.current.set(job.id, job.status);
      setNotice('it’s in the queue; poke around your other sets while it builds.');
      setRefresh(n => n + 1);
    } catch (error) { failed(error); }
    finally { setSending(false); }
  }
  const locked = sending || isDemo;
  const pending = jobs.filter(j => j.status !== 'succeeded');
  return <>
    <section className="create-area" aria-label="new build">
      {signedOut ? <div id="new-build" ref={newBuildRef} className="create-panel sign-in-card">
        <h2>what are we building?</h2>
        <p className="create-hint">describe it in a sentence or two, or hand over a photo; we’ll work out the bricks.</p>
        <p className="sign-in-note">sign in with google, top right, to start building; your sets will be waiting when you come back.</p>
      </div> : session && <form id="new-build" ref={newBuildRef} className="create-panel" onSubmit={submit}>
        <div className="create-intro">
          <h2>what are we building?</h2>
          <p className="create-hint">describe it in a sentence or two, or hand over a photo; we’ll work out the bricks.</p>
        </div>
        <div className="creation-modes" role="group" aria-label="generation source">
          <button type="button" aria-pressed={mode === 'text'} disabled={sending} onClick={() => { setMode('text'); setSubmitError(''); closeCamera(); }}>describe it</button>
          <button type="button" aria-pressed={mode === 'image'} disabled={sending} onClick={() => { setMode('image'); setSubmitError(''); }}>from a photo</button>
        </div>
        {mode === 'image' && <div className="upload-panel">
          <p className="prompt-label">the photo</p>
          <div className="image-source-actions" role="group" aria-label="where the photo comes from">
            <input ref={fileInput} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" disabled={locked || reading} onChange={chooseImage} />
            <button type="button" className="button secondary image-source-button" disabled={locked || reading} onClick={() => fileInput.current?.click()}>
              <span className="label-upload">upload a photo</span>
              <span className="label-gallery">choose from gallery</span>
            </button>
            <button type="button" className="button secondary image-source-button" disabled={locked || reading} onClick={openCamera}>take a photo</button>
          </div>
          <p className="upload-hint">png, jpeg or webp, up to 3 mb, 32–4096 pixels per side; one object in clear view works best. taking a photo asks for camera permission.</p>
          {reading && <p role="status">reading the image…</p>}
          {upload && <div className="upload-preview"><img src={upload.dataUrl} alt="reference photo for the new set" /><span>{upload.name}</span><button type="button" disabled={sending} onClick={removeImage}>remove</button></div>}
        </div>}
        <label className="prompt-label prompt-main">
          <span className={mode === 'text' ? 'visually-hidden' : ''}>{mode === 'text' ? 'describe the set' : 'anything we should know? (optional)'}</span>
          <textarea ref={promptRef} required={mode === 'text'} maxLength={2000} rows={mode === 'text' ? 4 : 2} value={description} onChange={e => setDescription(e.target.value)} placeholder={mode === 'text' ? 'a tiny green dinosaur with a yellow belly and a chunky tail…' : 'focus on the car, ignore the background, keep the red roof…'} disabled={locked} />
        </label>
        <div className="create-options">
          <label className="prompt-label">name <span>optional; we’ll think of one if you don’t</span><input value={name} onChange={e => setName(e.target.value)} maxLength={80} disabled={locked} /></label>
          <div className="size-controls">
            <div className="size-heading">
              <label className="prompt-label" htmlFor="max-size">size <span>longest side, in studs</span></label>
              {maxSize != null && <button type="button" className="text-button" disabled={locked} onClick={() => setMaxSize(null)}>back to auto</button>}
            </div>
            <div className="size-slider">
              <input id="max-size" type="range" min="16" max="32" step="4" list="size-stops" value={maxSize ?? 24} aria-valuetext={maxSize == null ? 'auto' : `${maxSize} studs`} disabled={locked} onChange={e => setMaxSize(Number(e.target.value))} />
              <datalist id="size-stops">{[16, 20, 24, 28, 32].map(size => <option key={size} value={size} />)}</datalist>
              <output>{maxSize == null ? 'auto' : `${maxSize} studs`}</output>
            </div>
            <small>{maxSize == null ? 'left on auto, we’ll pick a size that suits the thing; drag to choose one yourself.' : `we’ll keep the longest side to about ${maxSize} studs; press auto to let us choose.`}</small>
          </div>
          {mode === 'text' && <label className="stylize-toggle"><input type="checkbox" checked={stylize} disabled={locked} onChange={e => setStylize(e.target.checked)} /><span>flesh out short prompts<small>a quick model adds color and detail before the design starts; you’ll see what it wrote on the finished set.</small></span></label>}
        </div>
        <div className="prompt-footer">
          <button className="button primary" disabled={locked || paused || reading || (mode === 'text' ? !description.trim() : !upload)}>{sending ? 'sending it off…' : mode === 'image' ? 'build it from the photo' : 'build it'}</button>
          <small>{isDemo ? 'this is the static demo; start the local api to build sets.' : mode === 'image' ? 'your photo goes to the design model when you build, and anything it can’t see gets approximated; takes a few minutes and spends api credits.' : 'takes a few minutes; it does spend api credits.'}</small>
        </div>
        {submitError && <p className="form-error" role="alert">{submitError}</p>}
        {notice && <p className="form-notice" role="status">{notice}</p>}
      </form>}
      {pending.length > 0 && <div className="generation-jobs" aria-label="generation progress">{pending.map(job => <article className="job-row" key={job.id}>
        <div><strong>{job.name}</strong><small>{job.status !== 'failed' && <AssemblyIndicator />}{stageLabels[job.stage] || job.stage}</small></div>
        {job.status === 'failed' ? job.inputType === 'refine'
          ? <p role="status">{job.error?.message}<button type="button" onClick={() => pick(job.parentId)}>open the original</button></p>
          : <p role="status">{job.error?.message}<button type="button" onClick={() => { submission.current = null; setName(job.name); setDescription(job.description); setMode(job.inputType === 'image' ? 'image' : 'text'); removeImage(); setNotice(job.inputType === 'image' ? 'pick the photo again to retry.' : 'your description is back in the box; tweak it or send it as is.'); }}>use these inputs again</button></p>
          : <progress max="1" value={job.progress} aria-label={`${job.name}: ${stageLabels[job.stage] || job.stage}`} />}
      </article>)}</div>}
    </section>
    <div ref={workspaceRef} className="workspace-slot">{workspace}</div>
    <section id="library" ref={libraryRef} className="library" aria-label="library">
      <div className="library-heading">
        <div className="library-tabs" role="group" aria-label="library">
          <button type="button" aria-pressed={shown === 'mine'} onClick={() => setView('mine')}>my sets {libraryOpen && <span>{builds.length}</span>}</button>
          <button type="button" aria-pressed={shown === 'gallery'} onClick={() => setView('gallery')}>gallery</button>
        </div>
        <p>{shown === 'gallery' ? 'sets people chose to share; open one to look it over.' : session?.auth === 'google' ? 'saved to your google account.' : 'kept on this computer.'}</p>
      </div>
      {shown === 'mine' ? <>
        {signedOut && <p className="library-empty">sign in to see the sets you’ve saved.</p>}
        {loadError && libraryOpen && <p className="form-error" role="alert">{loadError}</p>}
        <div className="saved-builds">{builds.map(build => <SetCard key={build.id} build={build} selected={selectedId === build.id} onSelect={pick} />)}</div>
      </> : <>
        {gallery.error && <p className="form-error" role="alert">{gallery.error}</p>}
        {!galleryReady && <p className="library-empty" role="status">opening the gallery…</p>}
        {galleryReady && !gallery.items.length && !gallery.error && <p className="library-empty">nothing here yet; publish one of yours and be the first.</p>}
        <div className="saved-builds">{gallery.items.map(build => <SetCard key={build.id} build={build} selected={selectedId === build.id} onSelect={pick} byline />)}</div>
        {gallery.next && <button type="button" className="button secondary load-more" disabled={loadingMore} onClick={loadMore}>{loadingMore ? 'loading…' : 'load more'}</button>}
      </>}
    </section>
    {cameraOpen && <div className="camera-dialog" role="dialog" aria-modal="true" aria-label="take a reference photo">
      <div className="camera-sheet">
        <header>
          <h2>take a reference photo</h2>
          <button type="button" className="icon-button" aria-label="close camera" onClick={closeCamera}><X size={16} /></button>
        </header>
        <div className="camera-stage">
          {!cameraError && <video ref={videoRef} className="camera-preview" playsInline muted autoPlay />}
          {!cameraReady && !cameraError && <p className="camera-status" role="status">asking for camera permission…</p>}
          {cameraError && <p className="form-error" role="alert">{cameraError}</p>}
        </div>
        <footer>
          <button type="button" className="button secondary" onClick={closeCamera}>cancel</button>
          <button type="button" className="button primary" disabled={!cameraReady || !!cameraError} onClick={capturePhoto}>use this photo</button>
        </footer>
      </div>
    </div>}
  </>;
}

function SetCard({ build, selected, onSelect, byline = false }) {
  return <button type="button" aria-pressed={selected} className={`saved-build ${selected ? 'selected' : ''}`} onClick={() => onSelect(build.id)}>
    <span className="saved-build-thumb"><img src={assetUrl(build.assets.preview)} alt="" loading="lazy" /></span>
    <strong>{build.name}</strong>
    {byline && <span className="saved-build-byline">by {build.authorName || 'a builder'}</span>}
    <span className="saved-build-counts">{byline ? `${build.partCount} pieces` : `${build.partCount} pieces · ${build.stepCount} steps`}</span>
  </button>;
}
