export function readPreference(key, fallback) {
  try {
    const value = localStorage.getItem(key);
    return value === null ? fallback : JSON.parse(value);
  } catch { return fallback; }
}

export function writePreference(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Private browsing/storage quota. */ }
}

export function isSendKey(event) {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing
    && !event.nativeEvent?.isComposing && event.keyCode !== 229;
}
