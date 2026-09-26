import React, { useRef, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { api } from './api';

const limits = [19, 19, 59];
const axes = [['X', 'Width', 'studs'], ['Y', 'Depth', 'studs'], ['Z', 'Height', 'plates']];
const clamp = (value, axis) => Math.max(0, Math.min(limits[axis], value));

export default function RefinePanel({ build, selected, region, notice, onRegion, onClear, onQueued }) {
  const [prompt, setPrompt] = useState('');
  const [name, setName] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const submission = useRef(null);
  const setBound = (end, axis, value) => {
    if (!region || Number.isNaN(value)) return;
    const next = { min: [...region.min], max: [...region.max] };
    next[end][axis] = clamp(value, axis);
    if (next.min[axis] > next.max[axis]) next[end === 'min' ? 'max' : 'min'][axis] = next[end][axis];
    onRegion(next);
  };
  const grow = (up, side) => onRegion({
    min: region.min.map((v, a) => clamp(a < 2 ? v - side : v, a)),
    max: region.max.map((v, a) => clamp(a < 2 ? v + side : v + up, a)),
  });
  async function submit(event) {
    event.preventDefault();
    if (sending || !region || !prompt.trim()) return;
    const body = { prompt: prompt.trim(), region, ...(name.trim() ? { name: name.trim() } : {}) };
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
    <h3><Sparkles size={16} />Refine a region</h3>
    <p>Click bricks in the viewer to select them; drag still rotates. Only the boxed region is regenerated, and bricks outside it stay where they are.</p>
    <div className="refine-selection"><span>{selected.length ? `${selected.length} brick${selected.length === 1 ? '' : 's'} selected` : 'No bricks selected yet'}</span>{region && <button type="button" onClick={onClear}><X size={13} />Clear</button>}</div>
    {region && <>
      <div className="region-grid" role="group" aria-label="Region bounds">
        {axes.map(([axis, label, unit], a) => <label key={axis}><span>{label} <small>{axis}, {unit}</small></span>
          <input type="number" aria-label={`${label} from`} min="0" max={limits[a]} value={region.min[a]} onChange={e => setBound('min', a, e.target.valueAsNumber)} />
          <input type="number" aria-label={`${label} to`} min="0" max={limits[a]} value={region.max[a]} onChange={e => setBound('max', a, e.target.valueAsNumber)} />
        </label>)}
      </div>
      <div className="region-actions"><button type="button" onClick={() => grow(3, 0)}>Extend up one brick</button><button type="button" onClick={() => grow(0, 1)}>Widen one stud</button></div>
      <label className="prompt-label">What should change here?<textarea required maxLength={2000} rows={3} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Give the head a red cap with a short brim…" disabled={sending} /></label>
      <label className="prompt-label">New set name <span>(optional)</span><input value={name} onChange={e => setName(e.target.value)} placeholder={`${build.name} (refined)`.slice(0, 80)} maxLength={80} disabled={sending} /></label>
      <button className="button primary" disabled={sending || !prompt.trim()}><Sparkles size={16} />{sending ? 'Submitting…' : 'Refine region'}</button>
      <small>Saves a new set; this one stays unchanged. Uses API credits.</small>
    </>}
    {error && <p className="form-error" role="alert">{error}</p>}
    {notice && !region && <p className="form-notice" role="status">{notice}</p>}
  </form>;
}
