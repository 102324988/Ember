export const API_BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
export const WS_URL = `${API_BASE.replace(/^http/, 'ws')}/ws/chat`;

export async function getJSON(url, options = {}) {
  const { timeout = 10000, signal, ...request } = options;
  const abort = new AbortController();
  let timedOut = false;
  const cancel = () => abort.abort();
  if (signal?.aborted) cancel();
  else signal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(() => { timedOut = true; abort.abort(); }, timeout);
  try {
    const response = await fetch(url, { ...request, signal: abort.signal });
    let data;
    try { data = await response.json(); }
    catch (error) { if (response.ok) throw error; }
    if (!response.ok) throw new Error(data?.detail || `请求失败 (${response.status})`);
    return data;
  } catch (error) {
    if (timedOut) throw new Error('请求超时，请重试。');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}
