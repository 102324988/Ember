export const API_BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');
export const WS_URL = `${API_BASE.replace(/^http/, 'ws')}/ws/chat`;

export async function getJSON(url, options) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) throw new Error(data?.detail || `请求失败 (${response.status})`);
  return data;
}
