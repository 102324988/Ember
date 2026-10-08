import assert from 'node:assert/strict';
import test from 'node:test';
import { mergeHistory } from '../src/messageHistory.js';
import { getJSON } from '../src/api.js';

test('persisted history deduplicates live messages and preserves streaming text', () => {
  const current = [{ id: 'live', message_id: 'same', role: 'ai', timestamp: 2000, content: '正在回复', rawContent: '正在回复' }];
  const history = [{ id: 3, message_id: 'same', role: 'ai', timestamp: 2000, content: '已保存' },
    { id: 2, message_id: 'older', role: 'user', timestamp: 1000, content: '你好' }];
  const result = mergeHistory(current, history);
  assert.equal(result.length, 2);
  assert.equal(result[0].content, '你好');
  assert.equal(result[1].content, '正在回复');
  assert.equal(result[1].history_id, 3);
  assert.equal(mergeHistory(result, history).length, 2);
});

test('legacy inner monologue is not rendered as speech', () => {
  const result = mergeHistory([], [
    { id: 1, role: 'ai', content: '<thought>历史独白</thought>' },
    { id: 2, role: 'ai', content: '<thought>历史独白</thought><response>你好</response>' },
  ]);
  assert.equal(result[0].content, '');
  assert.equal(result[1].content, '你好');
});

test('HTTP errors propagate their actionable message', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: '数据库不可用' }) });
  try { await assert.rejects(getJSON('http://localhost/history'), /数据库不可用/); }
  finally { globalThis.fetch = original; }
});
