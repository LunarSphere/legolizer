import React, { useRef, useState } from 'react';
import { api } from './api';

export default function RefinePanel({ build, buildName, selected, notice, onClear, onQueued }) {
  const [prompt, setPrompt] = useState('');
  const [name, setName] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const submission = useRef(null);
  const count = selected.length;
  const title = buildName || build.name;
  async function submit(event) {
    event.preventDefault();
    if (sending || !prompt.trim()) return;
    const selection = selected.map(p => ({ min: p.min, max: p.max }));
    const body = { prompt: prompt.trim(), selection, ...(name.trim() ? { name: name.trim() } : {}) };
    const fingerprint = JSON.stringify([build.id, body]);
    if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, key: crypto.randomUUID() };
    setSending(true); setError('');
    try {
      const job = await api.refineBuild(build.id, body, submission.current.key);
      submission.current = null;
      setPrompt(''); setName('');
      onQueued(job);
    } catch (e) { setError(e.message); }
    finally { setSending(false); }
  }
  return <form className="refine-card" onSubmit={submit}>
    <h3>refine this set</h3>
    <p>{count
      ? 'only the picked bricks, plus one brick around each, can change; everything else stays put.'
      : 'click bricks in the viewer to keep the change to them (and one brick around each), or describe a change to the whole model; dragging still turns it.'}</p>
    <div className="refine-selection"><span>{count ? `${count} brick${count === 1 ? '' : 's'} picked` : 'nothing picked, so the whole model'}</span>{count > 0 && <button type="button" onClick={onClear}>clear</button>}</div>
    <label className="prompt-label">{count ? 'what should change in these bricks?' : `what should change about ${title}?`}<textarea required maxLength={2000} rows={3} value={prompt} onChange={e => { setPrompt(e.target.value); setError(''); }} placeholder={count ? 'give the head a red cap with a short brim…' : 'make the roof dark gray and add a chimney…'} disabled={sending} /></label>
    <label className="prompt-label">name for the new set <span>optional</span><input value={name} onChange={e => setName(e.target.value)} placeholder={`${title} (refined)`.slice(0, 80)} maxLength={80} disabled={sending} /></label>
    <button className="button primary" disabled={sending || !prompt.trim()}>{sending ? 'sending it off…' : count ? 'refine the picked bricks' : 'refine the whole model'}</button>
    <small>saves a new set, so {title} stays as it is; it does spend api credits.</small>
    {error && <p className="form-error" role="alert">{error}</p>}
    {notice && <p className="form-notice" role="status">{notice}</p>}
  </form>;
}
