const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');
export const buildId = import.meta.env.VITE_BUILD_ID || 'robot-corrected';
export const isDemo = import.meta.env.VITE_DEMO === 'true';
async function request(path, signal, options = {}) {
  let response;
  try { response = await fetch(path, { signal, ...options }); }
  catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('The local API is unavailable. Start the Python server and try again.');
  }
  let data;
  try { data = await response.json(); }
  catch { throw new Error('The local API is unavailable. Start the Python server and try again.'); }
  if (!response.ok) throw new Error(data.message || `Request failed (${response.status}).`);
  return data;
}
export function assetUrl(value) {
  const url = new URL(value, isDemo ? window.location.origin : new URL(`${base}/`, window.location.origin));
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Unsupported asset URL');
  return url.href;
}
export const api = {
  getBuild: (id, signal) => request(isDemo ? '/demo/build.json' : `${base}/builds/${encodeURIComponent(id)}`, signal),
  getParts: (id, signal) => request(isDemo ? '/demo/parts.json' : `${base}/builds/${encodeURIComponent(id)}/parts`, signal),
  async listBuilds(signal) {
    if (isDemo) return { items: [await request('/demo/build.json', signal)] };
    const items = [];
    let cursor = '';
    do {
      const page = await request(`${base}/builds?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`, signal);
      items.push(...page.items);
      cursor = page.nextCursor;
    } while (cursor);
    return { items };
  },
  getJobs: signal => isDemo ? Promise.resolve({ items: [] }) : request(`${base}/jobs`, signal),
  createBuild: (body, key) => request(`${base}/builds`, undefined, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(body),
  }),
  refineBuild: (id, body, key) => request(`${base}/builds/${encodeURIComponent(id)}/refinements`, undefined, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
    body: JSON.stringify(body),
  }),
};
