import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import {
  createViewerSocket,
  CLOSE_OVERFLOW,
  CLOSE_UNKNOWN_SESSION,
  type ViewerSocketDeps,
  type ViewerSocketLike,
  type ViewerState,
  type ViewerTerminal,
} from './viewer-socket';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '../../../..');

/** The real write-queue helpers, read off the module the terminal uses. */
function realQueue(): ViewerSocketDeps['queue'] {
  const sandbox: Record<string, unknown> = { console: { log() {} } };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(ROOT, 'client/js/terminal-write-queue.js'), 'utf8'),
    sandbox,
    { filename: 'terminal-write-queue.js' },
  );
  return sandbox.TerminalWriteQueue as ViewerSocketDeps['queue'];
}

const QUEUE = realQueue();

class FakeSocket implements ViewerSocketLike {
  binaryType = '';
  closed = 0;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  close(): void {
    this.closed += 1;
  }
}

class FakeTerm implements ViewerTerminal {
  resizes: Array<[number, number]> = [];
  writes: Uint8Array[] = [];
  disposed = 0;
  resize(cols: number, rows: number): void {
    this.resizes.push([cols, rows]);
  }
  write(data: Uint8Array | string): void {
    this.writes.push(typeof data === 'string' ? new TextEncoder().encode(data) : data);
  }
  dispose(): void {
    this.disposed += 1;
  }
}

function harness(opts: { autoOpen?: boolean } = {}) {
  const sockets: FakeSocket[] = [];
  const term = new FakeTerm();
  const states: ViewerState[] = [];
  const grids: Array<[number, number]> = [];
  let frameCb: (() => void) | null = null;
  const timers = new Map<number, { cb: () => void; ms: number }>();
  let handle = 0;
  const backoffs: number[] = [];

  const deps: ViewerSocketDeps = {
    openSocket: () => {
      const socket = new FakeSocket();
      sockets.push(socket);
      if (opts.autoOpen !== false) queueMicrotask(() => socket.onopen?.({}));
      return socket;
    },
    backoffMs: (attempt: number) => {
      backoffs.push(attempt);
      return attempt * 1000;
    },
    requestFrame: (cb: () => void) => {
      frameCb = cb;
      return 1;
    },
    cancelFrame: () => {
      frameCb = null;
    },
    setTimer: (cb: () => void, ms: number) => {
      handle += 1;
      timers.set(handle, { cb, ms });
      return handle;
    },
    clearTimer: (h: number) => {
      timers.delete(h);
    },
    queue: QUEUE,
  };

  const view = createViewerSocket({
    sessionId: 'ses_1',
    term,
    onState: (s) => states.push(s),
    onGrid: (c, r) => grids.push([c, r]),
    deps,
  });

  return {
    view,
    term,
    states,
    grids,
    sockets,
    backoffs,
    get live(): FakeSocket {
      return sockets[sockets.length - 1] as FakeSocket;
    },
    frame(): void {
      const cb = frameCb;
      frameCb = null;
      cb?.();
    },
    captureFrame(): (() => void) | null {
      return frameCb;
    },
    timersOfDelay(ms: number): void {
      for (const [h, entry] of [...timers.entries()]) {
        if (entry.ms <= ms) {
          timers.delete(h);
          entry.cb();
        }
      }
    },
    timerCount(): number {
      return timers.size;
    },
  };
}

function bytes(size: number, fill = 65): ArrayBuffer {
  return new Uint8Array(size).fill(fill).buffer;
}

describe('the paint sizes the emulator to the remote pane before it writes', () => {
  test('a terminal_size frame resizes, then the screen is written', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: JSON.stringify({ type: 'terminal_size', cols: 143, rows: 41 }) });
    expect(h.term.resizes).toEqual([[143, 41]]);
    expect(h.grids).toEqual([[143, 41]]);
    h.live.onmessage?.({ data: bytes(8) });
    expect(h.term.writes).toEqual([]);
    h.frame();
    expect(h.term.writes.length).toBe(1);
    expect(h.term.resizes).toEqual([[143, 41]]);
    h.view.destroy();
  });

  test('a malformed grid is never applied', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: JSON.stringify({ type: 'terminal_size', cols: 0, rows: 0 }) });
    h.live.onmessage?.({ data: '{not json' });
    expect(h.term.resizes).toEqual([]);
    h.view.destroy();
  });
});

describe('output is batched and flushed on the frame, with a timer backstop', () => {
  test('three chunks in one frame become one write', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: bytes(3, 1) });
    h.live.onmessage?.({ data: bytes(4, 2) });
    h.live.onmessage?.({ data: bytes(5, 3) });
    expect(h.term.writes).toEqual([]);
    h.frame();
    expect(h.term.writes.length).toBe(1);
    expect(h.term.writes[0]?.length).toBe(12);
    h.view.destroy();
  });

  test('a tab that never gets a frame still flushes on the backstop', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: bytes(6) });
    h.timersOfDelay(20);
    expect(h.term.writes.length).toBe(1);
    expect(h.term.writes[0]?.length).toBe(6);
    h.view.destroy();
  });
});

describe('the queue is bounded, sheds from the front and says so once', () => {
  test('an overflow drops whole chunks from the front and writes one marker', () => {
    const h = harness();
    h.view.start();
    const budget = QUEUE.MAX_QUEUED_BYTES;
    const chunk = 1024 * 1024;
    for (let i = 0; i < 4; i += 1) h.live.onmessage?.({ data: bytes(chunk, i + 1) });
    h.live.onmessage?.({ data: bytes(chunk, 9) });
    h.frame();
    expect(h.term.writes.length).toBe(1);
    const written = h.term.writes[0] as Uint8Array;
    expect(written.length).toBeLessThanOrEqual(budget);
    const text = new TextDecoder().decode(written);
    const markers = text.split('[cloude: dropped ').length - 1;
    expect(markers).toBe(1);
    const announced = Number(/dropped (\d+) bytes/.exec(text)?.[1]);
    expect(announced % chunk).toBe(0);
    expect(announced).toBe(2 * chunk);
    expect(written.indexOf(1)).toBe(-1);
    expect(written.indexOf(2)).toBe(-1);
    expect(written.indexOf(3)).toBeGreaterThan(-1);
    h.view.destroy();
  });
});

describe('the reconnect ladder tells its three close codes apart', () => {
  test('4404 is terminal: no retry, no timer', () => {
    const h = harness();
    h.view.start();
    h.live.onclose?.({ code: CLOSE_UNKNOWN_SESSION });
    expect(h.view.state).toBe('gone');
    expect(h.sockets.length).toBe(1);
    expect(h.timerCount()).toBe(0);
    h.view.destroy();
  });

  test('4429 clears the queue and reconnects once, then backs off', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: bytes(32) });
    h.live.onclose?.({ code: CLOSE_OVERFLOW });
    expect(h.sockets.length).toBe(2);
    expect(h.timerCount()).toBe(0);
    h.frame();
    expect(h.term.writes).toEqual([]);
    h.live.onclose?.({ code: CLOSE_OVERFLOW });
    expect(h.sockets.length).toBe(2);
    expect(h.backoffs).toEqual([1]);
    h.view.destroy();
  });

  test('any other close waits out the shared backoff curve, which grows', () => {
    const h = harness();
    h.view.start();
    h.live.onclose?.({ code: 1006 });
    expect(h.view.state).toBe('reconnecting');
    expect(h.backoffs).toEqual([1]);
    h.timersOfDelay(1000);
    expect(h.sockets.length).toBe(2);
    h.live.onclose?.({ code: 1006 });
    expect(h.backoffs).toEqual([1, 2]);
    h.view.destroy();
  });

  test('only bytes clear the backoff budget', () => {
    const h = harness();
    h.view.start();
    h.live.onclose?.({ code: 1006 });
    h.timersOfDelay(1000);
    h.live.onopen?.({});
    h.live.onclose?.({ code: 1006 });
    expect(h.backoffs).toEqual([1, 2]);
    h.timersOfDelay(2000);
    h.live.onmessage?.({ data: bytes(4) });
    h.live.onclose?.({ code: 1006 });
    expect(h.backoffs).toEqual([1, 2, 1]);
    h.view.destroy();
  });
});

describe('teardown closes everything it opened, and only once', () => {
  test('destroy closes the socket, disposes the emulator and is idempotent', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: bytes(16) });
    const socket = h.live;
    h.view.destroy();
    expect(socket.closed).toBe(1);
    expect(h.term.disposed).toBe(1);
    expect(socket.onmessage).toBe(null);
    expect(socket.onclose).toBe(null);
    expect(h.view.state).toBe('closed');
    h.view.destroy();
    expect(socket.closed).toBe(1);
    expect(h.term.disposed).toBe(1);
  });

  test('a destroy during a backoff never opens the socket it was waiting for', () => {
    const h = harness();
    h.view.start();
    h.live.onclose?.({ code: 1006 });
    expect(h.timerCount()).toBe(1);
    h.view.destroy();
    expect(h.timerCount()).toBe(0);
    h.timersOfDelay(60000);
    expect(h.sockets.length).toBe(1);
  });

  test('destroy detaches the handlers and cancels the armed frame', () => {
    const h = harness();
    h.view.start();
    h.live.onmessage?.({ data: bytes(8) });
    const socket = h.live;
    expect(h.captureFrame()).not.toBe(null);
    h.view.destroy();
    expect(h.captureFrame()).toBe(null);
    expect(h.timerCount()).toBe(0);
    expect(socket.onmessage).toBe(null);
    expect(h.term.writes).toEqual([]);
  });
});

describe('the url is the app`s own, and it asks for the read-only role', () => {
  test('openWebSocket builds observer=1 and the two-element subprotocol', () => {
    const opened: Array<[string, string[]]> = [];
    const sandbox: Record<string, unknown> = {
      console: { log() {}, warn() {}, debug() {}, info() {}, error() {} },
      localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
      fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
      location: { protocol: 'http:', host: 'box:43202' },
      WebSocket: class {
        constructor(url: string, protocols: string[]) {
          opened.push([url, protocols]);
        }
      },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/api.js'), 'utf8'), sandbox, {
      filename: 'api.js',
    });
    const api = sandbox.API as {
      getToken(): string;
      openWebSocket(id: string, path?: string, options?: { observer?: boolean }): unknown;
    };
    api.getToken = () => 'tok';
    api.openWebSocket('ses 7', '/ws/terminal', { observer: true });
    api.openWebSocket('ses 7');
    expect(opened[0]?.[0]).toBe('ws://box:43202/ws/terminal?session_id=ses%207&observer=1');
    expect(opened[0]?.[1]).toEqual(['cloude.jwt.v1', 'tok']);
    expect(opened[1]?.[0]).toBe('ws://box:43202/ws/terminal?session_id=ses%207');
  });

  test('the default seam asks the app builder for the observer role', () => {
    const calls: Array<[string | null, string | undefined, unknown]> = [];
    const priorApi = (globalThis as Record<string, unknown>).API;
    const priorQueue = (globalThis as Record<string, unknown>).TerminalWriteQueue;
    const priorPolicy = (globalThis as Record<string, unknown>).TerminalReconnectPolicy;
    (globalThis as Record<string, unknown>).API = {
      openWebSocket(id: string | null, p?: string, o?: unknown) {
        calls.push([id, p, o]);
        return new FakeSocket();
      },
    };
    (globalThis as Record<string, unknown>).TerminalWriteQueue = QUEUE;
    (globalThis as Record<string, unknown>).TerminalReconnectPolicy = { backoffMs: () => 1000 };
    try {
      const view = createViewerSocket({ sessionId: 'ses_9', term: new FakeTerm() });
      view.start();
      view.destroy();
    } finally {
      (globalThis as Record<string, unknown>).API = priorApi;
      (globalThis as Record<string, unknown>).TerminalWriteQueue = priorQueue;
      (globalThis as Record<string, unknown>).TerminalReconnectPolicy = priorPolicy;
    }
    expect(calls).toEqual([
      ['ses_9', '/ws/terminal', { observer: true, interactive: false }],
    ]);
  });
});
