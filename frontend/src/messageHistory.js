export const messageKey = message => message.message_id || `${message.role}:${message.id}`;

export function mergeHistory(current, incoming) {
  const byKey = new Map(current.map(message => [messageKey(message), message]));
  incoming.forEach(message => {
    // Legacy database rows may contain a whole thought block instead of speech.
    message = { ...message, content: (message.content || '').replace(/<thought>[\s\S]*?<\/thought>/gi, '').replace(/<\/?response>/gi, '').trim() };
    if (message.content.includes('<thought>')) message.content = '';
    const key = messageKey(message);
    const existing = byKey.get(key);
    byKey.set(key, existing
      ? { ...message, ...existing, history_id: message.id }
      : { ...message, history_id: message.id });
  });
  return [...byKey.values()].sort((a, b) => (a.timestamp || Infinity) - (b.timestamp || Infinity)
    || (a.history_id || 0) - (b.history_id || 0));
}
