import React, { useRef, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { api } from './api';

export default function RefinePanel({ build, selected, notice, onClear, onQueued }) {
  const [prompt, setPrompt] = useState('');
  const [name, setName] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const submission = useRef(null);
  const count = selected.length;
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
    <h3><Sparkles size={16} />Refine this set</h3>
    <p>{count
      ? 'Only the selected bricks and one brick around each can change; everything else stays where it is.'
      : 'Click bricks in the viewer to limit the edit to them and one brick around each, or describe a change to the whole model. Drag still rotates.'}</p>
    <div className="refine-selection"><span>{count ? `${count} brick${count === 1 ? '' : 's'} selected` : 'No bricks selected: whole model'}</span>{count > 0 && <button type="button" onClick={onClear}><X size={13} />Clear</button>}</div>
    <label className="prompt-label">{count ? 'What should change here?' : 'What should change?'}<textarea required maxLength={2000} rows={3} value={prompt} onChange={e => { setPrompt(e.target.value); setError(''); }} placeholder={count ? 'Give the head a red cap with a short brim…' : 'Make the roof dark gray and add a chimney…'} disabled={sending} /></label>
    <label className="prompt-label">New set name <span>(optional)</span><input value={name} onChange={e => setName(e.target.value)} placeholder={`${build.name} (refined)`.slice(0, 80)} maxLength={80} disabled={sending} /></label>
    <button className="button primary" disabled={sending || !prompt.trim()}><Sparkles size={16} />{sending ? 'Submitting…' : count ? 'Refine selection' : 'Refine whole model'}</button>
    <small>Saves a new set; this one stays unchanged. Uses API credits.</small>
    {error && <p className="form-error" role="alert">{error}</p>}
    {notice && <p className="form-notice" role="status">{notice}</p>}
  </form>;
}
