
'use strict';

function keyOf(name, row) {
  let key;
  if (name === 'list') key = row && row.session && row.session.id;
  else if (name === 'attachable') key = row && row.name;
  else key = row && row.session_uuid;
  return typeof key === 'string' ? key : null;
}

const RESYNC_RETRY_MIN_MS = 1000;
const RESYNC_RETRY_MAX_MS = 30000;

function emptyHeld() {
  return { byKey: new Map(), order: [], ok: true, detail: null };
}

class ListingStore {
  constructor(fetchSnapshot, timers) {
    this.fetch = fetchSnapshot;
    this.timers = timers || { setTimeout, clearTimeout };
    this.socketOpen = false;
    this.retryTimer = null;
    this.retryAttempt = 0;
    this.stream = null;
    this.seq = 0;
    this.live = false;
    this.syncing = null;
    this.generation = 0;
    this.buffered = [];
    this.cols = new Map();
    this.listeners = new Set();
    this.lastError = null;
  }

  isLive() {
    return this.live;
  }

  rows(name) {
    const held = this.cols.get(name);
    if (!held || !held.ok) return null;
    return held.order.filter((k) => held.byKey.has(k)).map((k) => held.byKey.get(k));
  }

  onChange(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  hello() {
    this.socketOpen = true;
    this.retryAttempt = 0;
    return this.resync();
  }

  closed() {
    this.socketOpen = false;
    this.cancelRetry();
    this.generation += 1;
    this.syncing = null;
    this.buffered = [];
    this.setLive(false);
  }

  frame(frame) {
    if (!frame || !Number.isInteger(frame.seq) || !frame.changes || typeof frame.changes !== 'object') return 'ignored';
    if (this.syncing) {
      this.buffered.push(frame);
      return 'buffered';
    }
    if (!this.live) return 'ignored';
    if (frame.stream !== this.stream || frame.seq > this.seq + 1) {
      this.resync();
      return 'resync';
    }
    if (frame.seq <= this.seq) return 'ignored';
    this.apply(frame);
    this.notify(Object.keys(frame.changes));
    return 'applied';
  }

  resync() {
    if (this.syncing) return this.syncing;
    this.buffered = [];
    this.generation += 1;
    const me = this.runResync(this.generation);
    this.syncing = me;
    return me;
  }

  async runResync(generation) {
    let snap;
    try {
      snap = await this.fetch();
    } catch (error) {
      if (generation !== this.generation) return;
      this.lastError = String((error && error.message) || error);
      this.syncing = null;
      this.setLive(false);
      this.notify(['$resync_failed']);
      this.scheduleRetry();
      return;
    }
    if (generation !== this.generation || !this.syncing) return;
    this.retryAttempt = 0;
    this.load(snap);
    const pending = this.buffered
      .filter((f) => f.stream === snap.stream && f.seq > Number(snap.seq || 0))
      .sort((a, b) => a.seq - b.seq);
    this.buffered = [];
    this.syncing = null;
    for (const f of pending) {
      if (f.seq !== this.seq + 1) {
        this.resync();
        return;
      }
      this.apply(f);
    }
    this.live = true;
    this.notify(['$live', ...this.cols.keys()]);
  }

  scheduleRetry() {
    if (!this.socketOpen || this.retryTimer) return;
    const delay = Math.min(RESYNC_RETRY_MAX_MS, RESYNC_RETRY_MIN_MS * 2 ** this.retryAttempt);
    this.retryAttempt += 1;
    this.retryTimer = this.timers.setTimeout(() => {
      this.retryTimer = null;
      if (this.socketOpen && !this.live) this.resync();
    }, delay);
  }

  cancelRetry() {
    if (this.retryTimer) this.timers.clearTimeout(this.retryTimer);
    this.retryTimer = null;
    this.retryAttempt = 0;
  }

  async poll() {
    const snap = await this.fetch();
    if (this.live || this.syncing) return;
    this.load(snap);
    this.notify([...this.cols.keys()]);
  }

  load(snap) {
    this.lastError = null;
    this.stream = snap && snap.stream !== undefined ? snap.stream : null;
    this.seq = Number((snap && snap.seq) || 0);
    this.cols.clear();
    const collections = (snap && snap.collections) || {};
    for (const [name, col] of Object.entries(collections)) {
      const held = emptyHeld();
      for (const row of (col && col.rows) || []) {
        const key = keyOf(name, row);
        if (key === null || held.byKey.has(key)) continue;
        held.byKey.set(key, row);
        held.order.push(key);
      }
      held.ok = !col || col.ok !== false;
      held.detail = (col && col.detail) || null;
      this.cols.set(name, held);
    }
  }

  apply(frame) {
    for (const [name, change] of Object.entries(frame.changes)) {
      if (!this.cols.has(name)) this.cols.set(name, emptyHeld());
      const held = this.cols.get(name);
      for (const up of (change && change.upsert) || []) {
        let row = held.byKey.get(up.key);
        if (!row) {
          row = {};
          held.byKey.set(up.key, row);
          held.order.push(up.key);
        }
        Object.assign(row, up.fields || {});
        for (const [field, part] of Object.entries(up.nested || {})) {
          const inner = row[field];
          row[field] = { ...(inner && typeof inner === 'object' ? inner : {}), ...part };
        }
        for (const field of up.drop || []) delete row[field];
      }
      for (const key of (change && change.remove) || []) held.byKey.delete(key);
      held.order = ((change && change.order) || held.order).filter((k) => held.byKey.has(k));
      if (change && change.status) {
        held.ok = change.status.ok !== false;
        held.detail = change.status.detail || null;
      }
    }
    this.seq = frame.seq;
  }

  setLive(on) {
    if (this.live !== on) {
      this.live = on;
      this.notify(['$live']);
    }
  }

  notify(names) {
    for (const fn of [...this.listeners]) {
      try {
        fn(names);
      } catch (error) {
        console.warn('[tray-menu] listing listener failed:', error && error.message);
      }
    }
  }
}

module.exports = { ListingStore, keyOf, RESYNC_RETRY_MIN_MS, RESYNC_RETRY_MAX_MS };
