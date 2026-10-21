// One owner for playback. Stopping sound never claims to cancel model generation.
export class AudioController {
  constructor(onChange, createAudio = source => new Audio(source)) {
    this.onChange = onChange;
    this.createAudio = createAudio;
    this.enabled = false;
    this.queue = [];
    this.knownMessages = new Set();
    this.suppressed = new Set();
    this.requests = new Set();
    this.current = null;
    this.version = 0;
  }

  notify(state, audio = null, error = '') { this.onChange({ state, audio, error }); }

  beginMessage(id) {
    if (!id) return;
    this.knownMessages.add(id);
    if (!this.enabled) this.suppressed.add(id);
    // Recent IDs only; no conversation text is retained here.
    if (this.knownMessages.size > 1024) {
      const oldest = this.knownMessages.values().next().value;
      this.knownMessages.delete(oldest);
      this.suppressed.delete(oldest);
    }
  }

  setEnabled(enabled) {
    this.enabled = enabled;
    if (!enabled) this.stop();
  }

  suppressMessage(id) {
    this.beginMessage(id);
    if (id) this.suppressed.add(id);
  }

  stop() {
    this.version += 1;
    this.knownMessages.forEach(id => this.suppressed.add(id));
    this.requests.clear();
    this.queue = [];
    if (this.current) {
      this.current.onended = null;
      this.current.onerror = null;
      this.current.pause();
      this.current.removeAttribute('src');
      this.current.load();
    }
    this.current = null;
    this.notify('idle');
  }

  request(id) {
    this.stop();
    this.requests.add(id);
    this.notify('loading');
  }

  failRequest(id, error) {
    if (!this.requests.delete(id)) return;
    this.notify('failed', null, error);
  }

  fail(event) {
    const error = event.content || '语音生成失败，请重试。';
    if (event.request_id) { this.failRequest(event.request_id, error); return; }
    if (!this.enabled || !this.knownMessages.has(event.message_id) || this.suppressed.has(event.message_id)
      || this.current || this.requests.size) return;
    this.notify('failed', null, error);
  }

  receive(event) {
    const manual = event.request_id && this.requests.delete(event.request_id);
    if (event.request_id && !manual) return;
    if (!manual && (!this.enabled || this.suppressed.has(event.message_id))) {
      this.beginMessage(event.message_id);
      return;
    }
    this.queue.push(event);
    this.playNext();
  }

  async playNext() {
    if (this.current || !this.queue.length) return;
    const event = this.queue.shift();
    const audio = this.createAudio(`data:audio/${event.format || 'mp3'};base64,${event.audio_base64 || event.content}`);
    const version = this.version;
    this.current = audio;
    const finish = () => {
      if (this.current !== audio) return;
      this.current = null;
      this.notify('idle');
      this.playNext();
    };
    audio.onended = finish;
    audio.onerror = () => {
      if (this.current !== audio) return;
      this.current = null;
      this.queue = [];
      this.notify('failed', null, '声音加载失败，可以重播这句。');
    };
    this.notify('loading');
    try {
      await audio.play();
      if (version !== this.version || this.current !== audio) { audio.pause(); return; }
      this.notify('playing', audio);
    } catch (error) {
      if (version !== this.version || this.current !== audio) return;
      this.current = null;
      this.queue = [];
      this.notify(error.name === 'NotAllowedError' ? 'blocked' : 'failed', null,
        error.name === 'NotAllowedError' ? '浏览器需要你点击“重播这句”后才能播放。' : '声音播放失败，可以重播这句。');
    }
  }
}
