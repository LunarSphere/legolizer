import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Plus, Box, ArrowRight, Camera, ImageUp, X } from 'lucide-react';
import { api, assetUrl, isDemo } from './api';
import AssemblyIndicator from './AssemblyIndicator';
import { GoogleButton } from './AccountMenu';

const stageLabels = { queued: 'Waiting in line', views: 'Imagining your set', scene: 'Planning the shape',
  assembly: 'Solving the bricks', render: 'Rendering the model', instructions: 'Making the build guide', complete: 'Saved to your library', failed: 'Build stopped' };
const ACCEPT_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
function cameraFailureMessage(error) {
  if (error?.name === 'NotAllowedError' || error?.name === 'PermissionDeniedError') {
    return 'Camera permission was denied. Allow camera access when prompted (or in browser settings), or upload an image instead.';
  }
  if (error?.name === 'NotFoundError' || error?.name === 'DevicesNotFoundError') {
    return 'No camera was found on this device. Upload an image instead.';
  }
  if (error?.name === 'NotReadableError' || error?.name === 'TrackStartError') {
    return 'The camera is already in use by another app. Close it and try again, or upload an image instead.';
  }
  if (error?.name === 'SecurityError') {
    return 'Camera access requires a secure context (HTTPS or localhost). Upload an image instead.';
  }
  return 'Unable to open the camera. Upload an image instead.';
}

export default function BuildLibrary({ selectedId, onSelect, refreshKey = 0, session, onSignIn }) {
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
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [maxSize, setMaxSize] = useState(null);
  const [stylize, setStylize] = useState(true);
  const [sizeHint, setSizeHint] = useState('');
  const [sizing, setSizing] = useState(false);
  const [sending, setSending] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
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
            setNotice(`${job.name} is ready and saved in your sets.`);
            if (job.buildId) openBuild.current(job.buildId);
          }
          if (job.status === 'failed' && previous && previous !== 'failed') {
            setNotice(`${job.name} stopped. See the failure details below; your saved sets are unchanged.`);
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
      setSubmitError('Choose a PNG, JPEG, or WebP image up to 3 MB.');
      if (inputEl) inputEl.value = '';
      return;
    }
    setReading(true);
    try {
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(new Error('Unable to read this image.'));
        reader.readAsDataURL(file);
      });
      const image = new Image();
      image.src = dataUrl;
      await image.decode();
      if (Math.max(image.width, image.height) > 4096 || Math.min(image.width, image.height) < 32) {
        throw new Error('Each image dimension must be between 32 and 4096 pixels.');
      }
      if (version === readVersion.current) setUpload({ name: file.name, dataUrl, mediaType: file.type, data: dataUrl.split(',')[1] });
    } catch (error) { if (version === readVersion.current) setSubmitError(error.message || 'Unable to open this image.'); }
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
      if (!context) throw new Error('Unable to capture this frame.');
      context.drawImage(video, 0, 0);
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(result => (result ? resolve(result) : reject(new Error('Unable to capture this frame.'))), 'image/jpeg', 0.92);
      });
      const file = new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
      closeCamera();
      await ingestFile(file);
    } catch (error) {
      setCameraError(error.message || 'Unable to capture this frame.');
    }
  }
  async function suggestSize() {
    if (sizing || sending || reading || (mode === 'text' ? !description.trim() : !upload)) return;
    setSizing(true); setSubmitError('');
    try {
      const body = {
        description: description.trim(),
        ...(mode === 'image' && upload ? { image: { mediaType: upload.mediaType, data: upload.data } } : {}),
      };
      const result = await api.estimateSize(body);
      setMaxSize(result.size);
      setSizeHint(result.reason);
    } catch (error) { setSubmitError(error.message); }
    finally { setSizing(false); }
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
      setDescription(''); setName(''); setMaxSize(null); setSizeHint(''); removeImage();
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
      latestJobs.current.set(job.id, job.status);
      setNotice('Your set is queued. You can explore saved sets while it builds.');
      setRefresh(n => n + 1);
    } catch (error) { setSubmitError(error.message); }
    finally { setSending(false); }
  }
  return <section className="creation-library" aria-label="Create and manage LEGO sets">
    {signedOut ? <div className="prompt-card sign-in-card">
      <div><p className="eyebrow">WHAT WILL YOU BUILD NEXT?</p><h2>Sign in to start building.</h2><p>Turn words or a picture into a LEGO set. Your sets are saved to your Google account, so they are here when you come back.</p></div>
      {session.googleClientId && <GoogleButton clientId={session.googleClientId} onCredential={onSignIn} />}
    </div> : session && <form className="prompt-card" onSubmit={submit}>
      <div><p className="eyebrow">WHAT WILL YOU BUILD NEXT?</p><h2>A new idea starts here.</h2><p>Start with words or a picture. Your existing sets stay saved.</p></div>
      <label className="prompt-label">Set name <span>(optional)</span><input value={name} onChange={e => setName(e.target.value)} placeholder="My next masterpiece" maxLength={80} disabled={sending || isDemo} /></label>
      <div className="creation-modes" role="group" aria-label="Generation source">
        <button type="button" aria-pressed={mode === 'text'} disabled={sending} onClick={() => { setMode('text'); setSubmitError(''); closeCamera(); }}>Text → LEGO</button>
        <button type="button" aria-pressed={mode === 'image'} disabled={sending} onClick={() => { setMode('image'); setSubmitError(''); }}>Image → LEGO</button>
      </div>
      {mode === 'image' && <div className="upload-panel">
        <p className="prompt-label">Reference image</p>
        <div className="image-source-actions" role="group" aria-label="Reference image source">
          <input ref={fileInput} className="visually-hidden" type="file" accept="image/png,image/jpeg,image/webp" disabled={sending || isDemo || reading} onChange={chooseImage} />
          <button type="button" className="button secondary image-source-button" disabled={sending || isDemo || reading} onClick={() => fileInput.current?.click()}>
            <ImageUp size={16} />
            <span className="label-upload">Upload image</span>
            <span className="label-gallery">Choose from gallery</span>
          </button>
          <button type="button" className="button secondary image-source-button" disabled={sending || isDemo || reading} onClick={openCamera}>
            <Camera size={16} />Take photo
          </button>
        </div>
        <p className="upload-hint">PNG, JPEG, or WebP · up to 3 MB · 32–4096 pixels per side. A clear view of one object works best. Taking a photo asks for camera permission.</p>
        {reading && <p role="status">Reading image…</p>}
        {upload && <div className="upload-preview"><img src={upload.dataUrl} alt="Reference for the new LEGO set" /><span>{upload.name}</span><button type="button" disabled={sending} onClick={removeImage}>Remove image</button></div>}
      </div>}
      <label className="prompt-label">{mode === 'text' ? 'Describe your LEGO set' : 'Additional guidance (optional)'}<textarea required={mode === 'text'} maxLength={2000} rows={3} value={description} onChange={e => setDescription(e.target.value)} placeholder={mode === 'text' ? 'A tiny green dinosaur with a yellow belly and a chunky tail…' : 'Focus on the car, ignore the background, and keep its red roof…'} disabled={sending || isDemo} /></label>
      {mode === 'text' && <label className="stylize-toggle"><input type="checkbox" checked={stylize} disabled={sending || isDemo} onChange={e => setStylize(e.target.checked)} /><span>Add detail and color<small>A quick model expands short prompts before designing. You’ll see the expanded prompt on the finished set.</small></span></label>}
      <div className="size-controls">
        <div className="size-heading">
          <label className="prompt-label" htmlFor="max-size">Build size <span>longest side in studs</span></label>
          <div className="size-actions">
            <button type="button" className="button secondary" disabled={sending || isDemo || sizing || reading || (mode === 'text' ? !description.trim() : !upload)} onClick={suggestSize}>{sizing ? 'Suggesting…' : 'Suggest size'}</button>
            <button type="button" className="button secondary" disabled={sending || isDemo || maxSize == null} onClick={() => { setMaxSize(null); setSizeHint(''); }}>Auto</button>
          </div>
        </div>
        <div className="size-slider">
          <input id="max-size" type="range" min="16" max="32" step="4" list="size-stops" value={maxSize ?? 24} aria-valuetext={maxSize == null ? 'Auto' : `${maxSize} studs`} disabled={sending || isDemo} onChange={e => { setMaxSize(Number(e.target.value)); setSizeHint(''); }} />
          <datalist id="size-stops">{[16, 20, 24, 28, 32].map(size => <option key={size} value={size} />)}</datalist>
          <output>{maxSize == null ? 'Auto' : `${maxSize} studs`}</output>
        </div>
        <small>{sizeHint || 'Auto asks a quick model for a size that fits the subject. Drag the slider to set one yourself.'}</small>
      </div>
      <div className="prompt-footer"><small>{isDemo ? 'Static demo mode. Start the local API to generate sets.' : mode === 'image' ? 'Your image is sent to the design model when you generate. Unseen details are approximated. Uses API credits.' : 'Generation takes a few minutes and uses your configured API credits.'}</small><button className="button primary" disabled={sending || isDemo || reading || (mode === 'text' ? !description.trim() : !upload)}><Plus size={16} />{sending ? 'Submitting…' : mode === 'image' ? 'Generate from image' : 'Generate set'}</button></div>
      {submitError && <p className="form-error" role="alert">{submitError}</p>}
      {notice && <p className="form-notice" role="status">{notice}</p>}
    </form>}
    {cameraOpen && <div className="camera-dialog" role="dialog" aria-modal="true" aria-label="Take a reference photo">
      <div className="camera-sheet">
        <header>
          <div>
            <p className="eyebrow">CAMERA</p>
            <h2>Take a reference photo</h2>
          </div>
          <button type="button" className="icon-button" aria-label="Close camera" onClick={closeCamera}><X size={16} /></button>
        </header>
        <div className="camera-stage">
          {!cameraError && <video ref={videoRef} className="camera-preview" playsInline muted autoPlay />}
          {!cameraReady && !cameraError && <p className="camera-status" role="status">Requesting camera permission…</p>}
          {cameraError && <p className="form-error" role="alert">{cameraError}</p>}
        </div>
        <footer>
          <button type="button" className="button secondary" onClick={closeCamera}>Cancel</button>
          <button type="button" className="button primary" disabled={!cameraReady || !!cameraError} onClick={capturePhoto}><Camera size={16} />Use photo</button>
        </footer>
      </div>
    </div>}
    {jobs.some(j => j.status !== 'succeeded') && <div className="generation-jobs" aria-label="Generation progress">{jobs.filter(j => j.status !== 'succeeded').map(job => <article className="job-row" key={job.id}><div><strong>{job.name}</strong><small>{job.status !== 'failed' && <AssemblyIndicator />}{stageLabels[job.stage] || job.stage}</small></div>{job.status === 'failed' ? job.inputType === 'refine' ? <p role="status">{job.error?.message}<button type="button" onClick={() => onSelect(job.parentId)}>Open the original set</button></p> : <p role="status">{job.error?.message}<button type="button" onClick={() => { submission.current = null; setName(job.name); setDescription(job.description); setMode(job.inputType === 'image' ? 'image' : 'text'); removeImage(); setNotice(job.inputType === 'image' ? 'Choose your reference image again to retry.' : 'Edit or resubmit your description.'); }}>Use these inputs again</button></p> : <progress max="1" value={job.progress} aria-label={`${job.name}: ${stageLabels[job.stage]}`} />}</article>)}</div>}
    <div className="library-heading"><h2><Box size={18} />Saved sets <span>{builds.length}</span></h2><small>{session?.auth === 'google' ? 'Saved to your Google account' : 'Kept on this computer'}</small></div>
    {signedOut && <p className="library-empty">Sign in to see the sets you have saved.</p>}
    {loadError && libraryOpen && <p className="form-error" role="alert">{loadError}</p>}
    <div className="saved-builds">{builds.map(build => <button type="button" key={build.id} aria-pressed={selectedId === build.id} className={`saved-build ${selectedId === build.id ? 'selected' : ''}`} onClick={() => onSelect(build.id)}><img src={assetUrl(build.assets.preview)} alt="" /><span><strong>{build.name}</strong><small>{build.partCount} pieces · {build.stepCount} steps</small></span><ArrowRight size={16} /></button>)}</div>
  </section>;
}
