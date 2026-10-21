import { useEffect, useRef, useState } from 'react';
import './App.css';
import Live2DViewer from './Live2DViewer';
import ArchiveModal from './ArchiveModal';
import ChatPanel from './components/ChatPanel';
import Modal from './components/Modal';
import useEmberSession from './useEmberSession';
import { readPreference, writePreference, isSendKey } from './preferences';
const connectionLabels = {
  connecting: '正在连接',
  online: '已连接',
  reconnecting: '连接中断 · 正在重连'
};
const phaseLabels = {
  sending: '正在发送…',
  preparing: '正在准备场景与回复…',
  generating: '正在回复…',
  tools: '正在使用工具…',
  stopping: '正在停止，请等待后台任务结束…',
  finalizing: '正在完成本轮收尾…',
  idle: '可以继续交谈'
};
const modes = {
  face_to_face: '面对面',
  remote: '远程交流',
  unknown: '交流方式待确认'
};
export default function App() {
  const [draft, setDraft] = useState(() => {
    const saved = readPreference('ember.draft.v1', '');
    return typeof saved === 'string' ? saved : '';
  });
  const [autoPlay, setAutoPlay] = useState(() => readPreference('autoPlay', false) === true);
  const [fontSize, setFontSize] = useState(() => Math.max(16, Math.min(24, Number(readPreference('ember.fontSize.v1', 18)) || 18)));
  const [view, setView] = useState(() => readPreference('ember.view.v1', 'stage') === 'chat' ? 'chat' : 'stage');
  const [panel, setPanel] = useState(null);
  const [composing, setComposing] = useState(false);
  const [queuedText, setQueuedText] = useState(null);
  const queueVersion = useRef(0);
  const input = useRef(null);
  const session = useEmberSession(autoPlay);
  const {
    config,
    playback
  } = session;
  const state = config?.state || {};
  const scene = state.scene || {};
  const name = config?.display_name || '依鸣';
  const paused = config?.status?.paused || config?.status?.scene?.ready === false;
  const sendDisabled = session.connection !== 'online' || session.busy || paused || !draft.trim();
  useEffect(() => {
    writePreference('ember.draft.v1', draft);
  }, [draft]);
  useEffect(() => {
    writePreference('autoPlay', autoPlay);
  }, [autoPlay]);
  useEffect(() => {
    writePreference('ember.fontSize.v1', fontSize);
  }, [fontSize]);
  useEffect(() => {
    writePreference('ember.view.v1', view);
  }, [view]);
  const edit = text => {
    setDraft(text);
    setPanel(null);
    requestAnimationFrame(() => input.current?.focus());
  };
  const send = event => {
    event?.preventDefault();
    if (composing) return;
    if (session.sendMessage(draft)) setDraft('');
  };
  const interruptAndSend = async () => {
    if (!draft.trim() || composing || queuedText !== null) return;
    const text = draft.trim();
    const version = ++queueVersion.current;
    setQueuedText(text);
    try {
      await session.cancelTurn();
      if (version === queueVersion.current && session.sendMessage(text)) {
        setDraft(current => current.trim() === text ? '' : current);
      }
    } catch { /* The session displays a recoverable error; keep the draft. */ }
    finally { if (version === queueVersion.current) setQueuedText(null); }
  };
  return <div className={`ember-app view-${view}`}>
  <header className="app-header">
    <a className="brand" href="#main" aria-label="Ember，回到陪伴">
      Ember
      <span>与你，此刻</span>
    </a>
    <nav aria-label="主要功能">
      <button aria-pressed={!panel} onClick={() => setPanel(null)}>陪伴</button>
      <button aria-pressed={panel === 'memories'} onClick={() => setPanel('memories')}>回忆</button>
      <button aria-pressed={panel === 'archive'} onClick={() => setPanel('archive')}>存档</button>
      <button aria-pressed={panel === 'settings'} onClick={() => setPanel('settings')}>设置</button>
    </nav>
    <span className={`connection connection-${session.connection}`} role="status">{connectionLabels[session.connection]}</span>
  </header>
  <div className="world-bar">
    <div className="world-facts">
      <time>{config?.logical_time || '正在同步世界时间'}</time>
      <span>{scene.character_location || '角色位置待确认'}</span>
      <span>{modes[scene.communication_mode] || modes.unknown}</span>
    </div>
    <div className="view-switch" role="group" aria-label="界面视图">
      <button aria-pressed={view === 'stage'} onClick={() => setView('stage')}>舞台优先</button>
      <button aria-pressed={view === 'chat'} onClick={() => setView('chat')}>对话优先</button>
    </div>
  </div>
  {(session.configError || config?.status?.database?.ready === false || config?.status?.long_term_memory?.ready === false || config?.status?.scene?.state === 'needs_confirmation') && <div className="service-notice" role="status">{session.configError}{config?.status?.database?.ready === false && ' 聊天保存服务异常，消息可能仍在等待保存。'}{config?.status?.long_term_memory?.ready === false && ' 长期记忆暂不可用。'}{config?.status?.scene?.state === 'needs_confirmation' && ' 当前活动待确认，可以在对话中说明。'}</div>}
  <main id="main" className="companion-layout">
    <section className="character-stage" aria-label={`${name}的舞台`}>
      <div className="stage-caption">
        <span className="eyebrow">WITH YOU</span>
        <h1>{name}</h1>
        <p>{scene.communication_mode === 'remote' ? '隔着屏幕，也可以好好聊聊。' : '留一点时间，给眼前的相处。'}</p>
      </div>
      <div className="stage-atmosphere" aria-hidden="true" />
      <Live2DViewer currentEmotion={session.emotion} audio={playback.audio} modelPath={config?.live2d?.model_path} />
      <div className="stage-footer">
        <button onClick={() => setPanel('scene')}>查看当前情境</button>
        <span>{scene.user_location ? `你在：${scene.user_location}` : '你的位置尚未确认'}</span>
      </div>
    </section>
    <div className="dialogue-workspace">
      <ChatPanel session={session} onEdit={edit} fontSize={fontSize} />
      <div className="session-feedback" role="status" aria-live="polite">
        <span className={session.busy ? 'working-label' : ''}>{paused ? '场景正在准备或存读档，请稍候' : session.busy ? session.phase === 'idle' ? '正在处理本轮对话…' : phaseLabels[session.phase] : phaseLabels.idle}</span>
        {session.busy && <small>可以编辑下一条草稿</small>}
      </div>
      {session.busy && config?.capabilities?.cancel_turn && ['running', 'stopping'].includes(session.activeTurn?.status) && <div className="turn-controls">
        <button onClick={() => session.cancelTurn().catch(() => {})} disabled={session.phase === 'stopping' || session.connection !== 'online'}>
          {session.phase === 'stopping' ? '正在停止…' : '停止生成'}</button>
        <button onClick={interruptAndSend} disabled={!draft.trim() || composing || queuedText !== null || session.connection !== 'online'}>
          {session.phase === 'stopping' ? '停止后发送草稿' : '打断并发送'}</button>
      </div>}
      {queuedText !== null && <div className="queued-draft" role="status"><span>停止后发送：{queuedText}</span>
        <button onClick={() => { queueVersion.current += 1; setQueuedText(null); }}>取消待发</button></div>}
      {session.notice && <div className="inline-notice" role="status">
        <span>{session.notice}</span>
        <button aria-label="关闭提示" onClick={() => session.setNotice('')}>关闭</button>
      </div>}
      {playback.error && <p className="audio-error" role="status">{playback.error}</p>}
      <form className="composer" onSubmit={send}>
        <label htmlFor="message-input" className="sr-only">对{name}说</label>
        <textarea id="message-input" ref={input} value={draft} rows={3} placeholder={`对${name}说……`} onChange={event => setDraft(event.target.value)} onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)} onKeyDown={event => {
            if (!composing && isSendKey(event)) send(event);
          }} />
        <div className="composer-toolbar">
          <div className="audio-controls">
            <button type="button" aria-pressed={autoPlay} onClick={() => setAutoPlay(value => !value)}>{autoPlay ? '自动声音：开' : '自动声音：关'}</button>
            {playback.state !== 'idle' && <button type="button" onClick={session.stopAudio}>{playback.state === 'loading' ? '取消等待声音' : '停止声音'}</button>}
          </div>
          <span className="keyboard-hint">Enter 发送 · Shift+Enter 换行</span>
          <button className="primary-button" type="submit" disabled={sendDisabled}>{session.busy ? '等待本轮完成' : '发送'}</button>
        </div>
      </form>
      <div className="suggested-actions" aria-label="对话建议">
        <button onClick={() => edit('最近在忙什么？')}>问问近况</button>
        <button onClick={() => edit('要不要一起自习一会儿？')}>邀请自习</button>
        <span>点击填入草稿，由你决定发送</span>
      </div>
    </div>
  </main>
  {panel === 'settings' && <Modal title="设置" onClose={() => setPanel(null)}>
    <section className="settings-section">
      <h3>声音与文字</h3>
      <label className="setting-row">
        <span>自动播放回复声音</span>
        <input type="checkbox" checked={autoPlay} onChange={event => setAutoPlay(event.target.checked)} />
      </label>
      <p className="muted">关闭会停止当前声音并清空待播队列。每条回复仍可手动重播。</p>
      <label className="setting-row" htmlFor="font-size">
        <span>对白字号</span>
        <output>{fontSize}px</output>
      </label>
      <input id="font-size" type="range" min="16" max="24" value={fontSize} onChange={event => setFontSize(Number(event.target.value))} />
    </section>
    <section className="settings-section">
      <h3>显示</h3>
      <p>切换舞台与对话视图只改变布局，不改变世界时间或双方位置。</p>
      <p>草稿和显示偏好保存在当前浏览器。</p>
    </section>
    <section className="settings-section">
      <h3>服务状态</h3>
      <dl className="fact-list">
        <dt>聊天数据库</dt>
        <dd>{config?.status?.database?.ready ? '就绪' : '未就绪'}</dd>
        <dt>长期记忆</dt>
        <dd>{config?.status?.long_term_memory?.ready ? '就绪' : '未就绪'}</dd>
        <dt>场景</dt>
        <dd>{config?.status?.scene?.ready ? '就绪' : '准备中'}</dd>
      </dl>
      {config?.status?.configuration_warnings?.map(warning => <p className="inline-error" key={warning}>{warning}</p>)}
      <button onClick={() => setPanel('observer')}>打开观察面板</button>
    </section>
  </Modal>}
  {panel === 'scene' && <Modal title="当前情境" onClose={() => setPanel(null)}>
    <dl className="fact-list">
      <dt>角色位置</dt>
      <dd>{scene.character_location || '未知'}</dd>
      <dt>你的位置</dt>
      <dd>{scene.user_location || '未知'}</dd>
      <dt>交流方式</dt>
      <dd>{modes[scene.communication_mode] || modes.unknown}</dd>
      <dt>远程联系方式</dt>
      <dd>{scene.remote_contact_confirmed ? '已确认' : '尚未确认'}</dd>
    </dl>
    <p className="scene-description">{state['客观情境'] || '场景尚在同步。'}</p>
    <p className="muted">如有变化，请在对话中说明你的移动或交流方式。</p>
    <button onClick={() => edit('我想确认一下我们现在的位置和交流方式。')}>在对话中确认</button>
  </Modal>}
  {panel === 'memories' && <Modal title="回忆" onClose={() => setPanel(null)}>
    <h3>近期轨迹</h3>
    <p className="muted">来自当前角色状态；可能包含离线推演，不能替代原始对话记录。</p>
    <ol className="memory-trail">{(state['近期综合轨迹'] || '还没有可展示的轨迹').split(/->|→/).map((item, index) => <li key={index}>{item.trim()}</li>)}</ol>
    <button onClick={() => {
        setPanel(null);
        session.loadHistory();
      }}>回到对话记录</button>
  </Modal>}
  {panel === 'observer' && <Modal title="观察面板" onClose={() => setPanel(null)}>
    <p className="muted">角色内部状态与生成独白，供调试和观察。</p>
    <dl className="fact-list">{['P', 'A', 'D'].map(key => <div className="fact-pair" key={key}>
        <dt>{key}</dt>
        <dd>{state[key] ?? '未知'}</dd>
      </div>)}</dl>
    <h3>内心活动</h3>
    <p className="preserve-text">{state['内心活动'] || '暂无'}</p>
    <h3>近期目标</h3>
    <p>{state['近期目标'] || '暂无'}</p>
    <h3>本轮角色独白</h3>
    <p className="preserve-text">{session.thought || '本轮暂无可展示的独白'}</p>
  </Modal>}
  <ArchiveModal isOpen={panel === 'archive'} onClose={() => setPanel(null)} />
  </div>;
}
