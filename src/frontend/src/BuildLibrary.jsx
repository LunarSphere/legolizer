import React, { useEffect, useRef, useState } from 'react';
import { Plus, Box, ArrowRight } from 'lucide-react';
import { api, assetUrl, isDemo } from './api';

const stageLabels = { queued: 'Waiting in line', views: 'Imagining your set', scene: 'Planning the shape',
  assembly: 'Solving the bricks', render: 'Rendering the model', instructions: 'Making the build guide', complete: 'Saved to your library', failed: 'Build stopped' };
export default function BuildLibrary({ selectedId, onSelect }) {
  const [builds, setBuilds] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [mode, setMode] = useState('text');
  const [upload, setUpload] = useState(null);
  const [reading, setReading] = useState(false);
  const fileInput = useRef(null);
  const readVersion = useRef(0);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [sending, setSending] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [loadError, setLoadError] = useState('');
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const submission = useRef(null);
  const latestJobs = useRef(new Map());
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    const load = async () => {
      try {
        const [library, progress] = await Promise.all([api.listBuilds(controller.signal), api.getJobs(controller.signal)]);
        if (controller.signal.aborted) return;
        setBuilds(library.items);
        setJobs(progress.items);
        setLoadError('');
        for (const job of progress.items) {
          const previous = latestJobs.current.get(job.id);
          if (job.status === 'succeeded' && previous && previous !== 'succeeded') {
            setNotice(`${job.name} is ready and saved. Choose it below to explore.`);
          }
          if (job.status === 'failed' && previous && previous !== 'failed') {
            setNotice(`${job.name} stopped. See the failure details below; your saved sets are unchanged.`);
          }
          latestJobs.current.set(job.id, job.status);
        }
      } catch (error) {
        if (error.name !== 'AbortError') setLoadError(error.message);
      } finally {
        if (!controller.signal.aborted && !isDemo) timer = setTimeout(load, 4000);
      }
    };
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [refresh]);
  async function chooseImage(event) {
    const version = ++readVersion.current;
    const file = event.target.files?.[0];
    setUpload(null); setSubmitError(''); setReading(false);
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 4 * 1024 * 1024 || !file.size) {
      setSubmitError('Choose a PNG, JPEG, or WebP image up to 4 MB.');
      event.target.value = ''; return;
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
  function removeImage() {
    readVersion.current++; setReading(false); setUpload(null);
    if (fileInput.current) fileInput.current.value = '';
  }
  async function submit(event) {
    event.preventDefault();
    if (sending || reading || (mode === 'text' ? !description.trim() : !upload)) return;
    const body = { description: description.trim(), ...(name.trim() ? { name: name.trim() } : {}),
      ...(mode === 'image' ? { image: { mediaType: upload.mediaType, data: upload.data } } : {}) };
    const fingerprint = JSON.stringify(body);
    if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, key: crypto.randomUUID() };
    setSending(true); setSubmitError(''); setNotice('');
    try {
      const job = await api.createBuild(body, submission.current.key);
      submission.current = null;
      setDescription(''); setName(''); removeImage();
      setJobs(current => [job, ...current.filter(item => item.id !== job.id)]);
      latestJobs.current.set(job.id, job.status);
      setNotice('Your set is queued. You can explore saved sets while it builds.');
      setRefresh(n => n + 1);
    } catch (error) { setSubmitError(error.message); }
    finally { setSending(false); }
  }
  return <section className="creation-library" aria-label="Create and manage LEGO sets">
    <form className="prompt-card" onSubmit={submit}>
      <div><p className="eyebrow">WHAT WILL YOU BUILD NEXT?</p><h2>A new idea starts here.</h2><p>Start with words or a picture. Your existing sets stay saved.</p></div>
      <label className="prompt-label">Set name <span>(optional)</span><input value={name} onChange={e => setName(e.target.value)} placeholder="My next masterpiece" maxLength={80} disabled={sending || isDemo} /></label>
      <div className="creation-modes" role="group" aria-label="Generation source">
        <button type="button" aria-pressed={mode === 'text'} disabled={sending} onClick={() => { setMode('text'); setSubmitError(''); }}>Text → LEGO</button>
        <button type="button" aria-pressed={mode === 'image'} disabled={sending} onClick={() => { setMode('image'); setSubmitError(''); }}>Image → LEGO</button>
      </div>
      {mode === 'image' && <div className="upload-panel">
        <label className="prompt-label">Reference image<input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" disabled={sending || isDemo} onChange={chooseImage} /></label>
        <p>PNG, JPEG, or WebP · up to 4 MB · 32–4096 pixels per side. A clear view of one object works best.</p>
        {reading && <p role="status">Reading image…</p>}
        {upload && <div className="upload-preview"><img src={upload.dataUrl} alt="Reference for the new LEGO set" /><span>{upload.name}</span><button type="button" disabled={sending} onClick={removeImage}>Remove image</button></div>}
      </div>}
      <label className="prompt-label">{mode === 'text' ? 'Describe your LEGO set' : 'Additional guidance (optional)'}<textarea required={mode === 'text'} maxLength={2000} rows={3} value={description} onChange={e => setDescription(e.target.value)} placeholder={mode === 'text' ? 'A tiny green dinosaur with a yellow belly and a chunky tail…' : 'Focus on the car, ignore the background, and keep its red roof…'} disabled={sending || isDemo} /></label>
      <div className="prompt-footer"><small>{isDemo ? 'Static demo mode. Start the local API to generate sets.' : mode === 'image' ? 'Your image is sent to the design model when you generate. Unseen details are approximated. Uses API credits.' : 'Generation takes a few minutes and uses your configured API credits.'}</small><button className="button primary" disabled={sending || isDemo || reading || (mode === 'text' ? !description.trim() : !upload)}><Plus size={16} />{sending ? 'Submitting…' : mode === 'image' ? 'Generate from image' : 'Generate set'}</button></div>
      {submitError && <p className="form-error" role="alert">{submitError}</p>}
      {notice && <p className="form-notice" role="status">{notice}</p>}
    </form>
    {jobs.some(j => j.status !== 'succeeded') && <div className="generation-jobs" aria-label="Generation progress">{jobs.filter(j => j.status !== 'succeeded').map(job => <article className="job-row" key={job.id}><div><strong>{job.name}</strong><small>{stageLabels[job.stage] || job.stage}</small></div>{job.status === 'failed' ? <p role="status">{job.error?.message}<button type="button" onClick={() => { submission.current = null; setName(job.name); setDescription(job.description); setMode(job.inputType === 'image' ? 'image' : 'text'); removeImage(); setNotice(job.inputType === 'image' ? 'Choose your reference image again to retry.' : 'Edit or resubmit your description.'); }}>Use these inputs again</button></p> : <progress max="1" value={job.progress} aria-label={`${job.name}: ${stageLabels[job.stage]}`} />}</article>)}</div>}
    <div className="library-heading"><h2><Box size={18} />Saved sets <span>{builds.length}</span></h2><small>Kept on this computer</small></div>
    {loadError && <p className="form-error" role="alert">{loadError}</p>}
    <div className="saved-builds">{builds.map(build => <button type="button" key={build.id} aria-pressed={selectedId === build.id} className={`saved-build ${selectedId === build.id ? 'selected' : ''}`} onClick={() => onSelect(build.id)}><img src={assetUrl(build.assets.preview)} alt="" /><span><strong>{build.name}</strong><small>{build.partCount} pieces · {build.stepCount} steps</small></span><ArrowRight size={16} /></button>)}</div>
  </section>;
}
