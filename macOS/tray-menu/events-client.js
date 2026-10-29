
'use strict';

const SUBPROTOCOL_MARKER = 'cloude.jwt.v1';
const EVENTS_PATH = '/ws/events';
const POLL_MS = 20000;
const BACKOFF_MIN_MS = 1000;
const BACKOFF_MAX_MS = 30000;

function eventsUrl(baseUrl) {
  return String(baseUrl).replace(/\/+$/, '').replace(/^http/, 'ws') + EVENTS_PATH;
}

function backoffDelay(attempt, rng) {
  const base = Math.min(BACKOFF_MAX_MS, BACKOFF_MIN_MS * 2 ** Math.max(0, attempt));
  return Math.round(base * (1 + 0.25 * rng()));
}

class EventsClient {
  constructor(deps) {
    this.deps = deps;
    this.WS = deps.WebSocketImpl || global.WebSocket;
    this.timers = deps.timers || { setTimeout, clearTimeout, setInterval, clearInterval };
    this.rng = deps.rng || Math.random;
    this.ws = null;
    this.running = false;
    this.connected = false;
    this.attempt = 0;
    this.failuresBeforeHello = 0;
    this.retryTimer = null;
    this.pollTimer = null;
    this.generation = 0;
    if (typeof deps.store.onChange === 'function') {
      deps.store.onChange((names) => {
        if (!this.running || !(names.includes('$live') || names.includes('$resync_failed'))) return;
        if (deps.store.isLive()) this.stopPoll();
        else this.startPoll();
      });
    }
  }

  start() {
    if (this.running) return;
    this.running = true;
    this.connect();
  }

  stop() {
    this.running = false;
    this.generation += 1;
    if (this.retryTimer) this.timers.clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.stopPoll();
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      try {
        ws.close();
      } catch (error) {
      }
    }
    this.connected = false;
    this.deps.store.closed();
  }

  async connect() {
    if (!this.running) return;
    this.generation += 1;
    const gen = this.generation;
    const base = this.deps.getBaseUrl();
    const token = base ? await this.deps.getToken() : null;
    if (!this.running || gen !== this.generation) return;
    if (!base || !token || typeof this.WS !== 'function') {
      this.goDown();
      return;
    }
    let ws;
    try {
      ws = new this.WS(eventsUrl(base), [SUBPROTOCOL_MARKER, token]);
    } catch (error) {
      console.warn('[tray-menu] events socket could not be opened:', error && error.message);
      this.goDown();
      return;
    }
    this.ws = ws;
    ws.onmessage = (event) => this.dispatch(event && event.data);
    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.goDown();
    };
    ws.onerror = () => {};
  }

  dispatch(raw) {
    let frame;
    try {
      frame = JSON.parse(String(raw));
    } catch (error) {
      return;
    }
    const kind = frame && frame.type;
    if (kind === 'events.hello') this.hello(frame);
    else if (kind === 'listing.delta') this.deps.store.frame(frame);
    else if (kind === 'approvals' && this.deps.onApprovals) this.deps.onApprovals(frame);
    else if (kind === 'resources.changed' && this.deps.onTopics) {
      this.deps.onTopics((Array.isArray(frame.topics) ? frame.topics : []).filter((t) => typeof t === 'string'));
    }
  }

  hello(frame) {
    this.connected = true;
    this.attempt = 0;
    this.failuresBeforeHello = 0;
    this.stopPoll();
    this.deps.store.hello();
    if (this.deps.onState) this.deps.onState(true);
    if (this.deps.onHello) {
      const topics = frame && Array.isArray(frame.resource_topics) ? frame.resource_topics : [];
      this.deps.onHello(topics.filter((t) => typeof t === 'string'));
    }
    if (this.deps.onApprovals) this.deps.onApprovals(null);
  }

  goDown() {
    const wasConnected = this.connected;
    this.connected = false;
    this.deps.store.closed();
    if (!wasConnected) {
      this.failuresBeforeHello += 1;
      if (this.failuresBeforeHello >= 2) {
        this.deps.forgetToken();
        this.failuresBeforeHello = 0;
      }
    }
    if (this.deps.onState) this.deps.onState(false);
    if (!this.running) return;
    this.startPoll();
    const delay = backoffDelay(this.attempt, this.rng);
    this.attempt += 1;
    if (this.retryTimer) this.timers.clearTimeout(this.retryTimer);
    this.retryTimer = this.timers.setTimeout(() => {
      this.retryTimer = null;
      this.connect();
    }, delay);
  }

  startPoll() {
    if (this.pollTimer) return;
    const tick = () => {
      this.deps.store.poll().catch((error) => {
        this.deps.store.lastError = String((error && error.message) || error);
      });
    };
    tick();
    this.pollTimer = this.timers.setInterval(tick, POLL_MS);
  }

  stopPoll() {
    if (this.pollTimer) this.timers.clearInterval(this.pollTimer);
    this.pollTimer = null;
  }
}

module.exports = { SUBPROTOCOL_MARKER, EVENTS_PATH, POLL_MS, eventsUrl, backoffDelay, EventsClient };
