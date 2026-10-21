export const messageKey = message => message.message_id || `${message.role}:${message.id}`;

export function parseAssistantText(raw = '') {
  raw = raw.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '');
  const toolStart = raw.toLowerCase().indexOf('<tool_call>');
  if (toolStart >= 0) raw = raw.slice(0, toolStart);
  const tagStart = raw.lastIndexOf('<');
  if (tagStart >= 0 && ['<thought>', '</thought>', '<response>', '</response>', '<tool_call>', '</tool_call>']
    .some(tag => tag.startsWith(raw.slice(tagStart).toLowerCase()))) raw = raw.slice(0, tagStart);
  const lower = raw.toLowerCase();
  const start = lower.indexOf('<thought>');
  const end = lower.lastIndexOf('</thought>');
  const thought = start < 0 ? '' : raw.slice(start + 9, end < start ? undefined : end).trim();
  let speech = start >= 0 && end < start ? '' : end >= 0 ? raw.slice(end + 10) : raw;
  speech = speech.replace(/<\/?response>/gi, '').trim();
  return { thought, speech };
}

export function applyMessage(current, event) {
  const role = ['ai', 'assistant', 'bot'].includes(event.sender) ? 'ai' : 'user';
  const id = event.message_id || event.id;
  const index = current.findIndex(message => (message.message_id || message.id) === id
    || (event.client_request_id && message.client_request_id === event.client_request_id));
  const previous = index < 0 ? {} : current[index];
  const rawContent = event.mode === 'append' ? (previous.rawContent || previous.content || '') + (event.content || '') : event.content || '';
  const content = role === 'ai' ? parseAssistantText(rawContent).speech : rawContent;
  const message = { ...previous, role, id, message_id: id, client_request_id: event.client_request_id || previous.client_request_id,
    content, rawContent, streaming: role === 'ai' && ['start', 'append'].includes(event.mode),
    turn_id: event.turn_id || previous.turn_id,
    completion_status: event.completion_status || previous.completion_status || 'completed',
    timestamp: event.timestamp || previous.timestamp, delivery: event.persisted || previous.delivery === 'persisted' ? 'persisted' : 'received' };
  if (index < 0) return [...current, message];
  return current.map((item, i) => i === index ? message : item);
}

export function mergeHistory(current, incoming) {
  const byKey = new Map(current.map(message => [messageKey(message), message]));
  incoming.forEach(message => {
    // Legacy database rows may contain a whole thought block instead of speech.
    message = { ...message, content: (message.content || '').replace(/<thought>[\s\S]*?<\/thought>/gi, '').replace(/<\/?response>/gi, '').trim() };
    if (message.content.includes('<thought>')) message.content = '';
    const key = messageKey(message);
    const existing = byKey.get(key);
    const restoreFinal = existing?.role === 'ai' && existing.streaming === false;
    byKey.set(key, existing
      ? { ...message, ...existing, ...(restoreFinal ? { content: message.content, rawContent: message.content } : {}),
        completion_status: message.completion_status || existing.completion_status || 'completed',
        turn_id: message.turn_id || existing.turn_id,
        timestamp: message.timestamp, history_id: message.id, delivery: 'persisted' }
      : { ...message, history_id: message.id, delivery: 'persisted' });
  });
  return [...byKey.values()].sort((a, b) => (a.timestamp || Infinity) - (b.timestamp || Infinity)
    || (a.history_id || 0) - (b.history_id || 0));
}
