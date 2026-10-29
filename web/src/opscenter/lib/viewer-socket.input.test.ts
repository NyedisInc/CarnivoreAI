import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';

import {
  createViewerSocket,
  type InputTicket,
  type ViewerSocket,
  type ViewerSocketDeps,
  type ViewerSocketLike,
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
const DECODER = new TextDecoder();

class FakeSocket implements ViewerSocketLike {
  binaryType = '';
  closed = 0;
  sent: string[] = [];
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  send(data: Uint8Array | string): void {
    this.sent.push(typeof data === 'string' ? data : DECODER.decode(data));
  }
  close(): void {
    this.closed += 1;
  }
}

class FakeTerm implements ViewerTerminal {
  disposed = 0;
  resize(): void {}
  write(): void {}
  dispose(): void {
    this.disposed += 1;
  }
}

function view(sessionId: string, interactive: boolean) {
  const sockets: FakeSocket[] = [];
  const asked: boolean[] = [];
  const timers = new Map<number, () => void>();
  let handle = 0;

  const deps: ViewerSocketDeps = {
    openSocket: (_id: string, wantsInput: boolean) => {
      asked.push(wantsInput);
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    },
    backoffMs: () => 1000,
    requestFrame: () => 1,
    cancelFrame: () => {},
    setTimer: (cb: () => void) => {
      handle += 1;
      timers.set(handle, cb);
      return handle;
    },
    clearTimer: (h: number) => {
      timers.delete(h);
    },
    queue: QUEUE,
  };

  const handleOut: ViewerSocket = createViewerSocket({
    sessionId,
    term: new FakeTerm(),
    interactive,
    deps,
  });
  handleOut.start();

  return {
    view: handleOut,
    sockets,
    asked,
    get live(): FakeSocket {
      return sockets[sockets.length - 1] as FakeSocket;
    },
    open(): void {
      this.live.onopen?.({});
    },
    reconnect(): void {
      this.live.onclose?.({ code: 1006 });
      for (const [h, cb] of [...timers.entries()]) {
        timers.delete(h);
        cb();
      }
      this.open();
    },
    allSent(): string[] {
      return sockets.flatMap((socket) => socket.sent);
    },
  };
}

function type(v: ReturnType<typeof view>, data: string): boolean {
  const ticket = v.view.claimInput();
  return v.view.send(data, ticket);
}

describe('bytes typed into a cell reach that cell`s session and no other', () => {
  test('two views over two sessions never cross', () => {
    const a = view('ses_a', true);
    const b = view('ses_b', true);
    a.open();
    b.open();

    expect(type(a, 'ls\r')).toBe(true);
    expect(type(b, 'pwd\r')).toBe(true);

    expect(a.allSent()).toEqual(['ls\r']);
    expect(b.allSent()).toEqual(['pwd\r']);
  });

  test('the socket is opened asking for input, and a read-only one is not', () => {
    expect(view('ses_a', true).asked).toEqual([true]);
    expect(view('ses_a', false).asked).toEqual([false]);
  });

  test('a view that was not opened for input refuses to write at all', () => {
    const v = view('ses_a', false);
    v.open();
    expect(v.view.interactive).toBe(false);
    expect(type(v, 'rm -rf /\r')).toBe(false);
    expect(v.allSent()).toEqual([]);
  });
});

describe('a claim is taken at the gesture and spent at the write', () => {
  test('a ticket from before a reconnect is refused after it', () => {
    const v = view('ses_a', true);
    v.open();
    const stale: InputTicket = v.view.claimInput();

    v.reconnect();

    expect(v.view.send('rm -rf /\r', stale)).toBe(false);
    expect(v.allSent()).toEqual([]);

    expect(type(v, 'ls\r')).toBe(true);
    expect(v.allSent()).toEqual(['ls\r']);
  });

  test('a ticket naming another session is refused', () => {
    const v = view('ses_a', true);
    v.open();
    const foreign: InputTicket = { session: 'ses_b', connection: 1 };
    expect(v.view.send('ls\r', foreign)).toBe(false);
    expect(v.allSent()).toEqual([]);
  });

  test('nothing is written before the socket opens, and everything after', () => {
    const v = view('ses_a', true);
    expect(type(v, 'ls\r')).toBe(false);
    expect(v.allSent()).toEqual([]);
    v.open();
    expect(type(v, 'ls\r')).toBe(true);
    expect(v.allSent()).toEqual(['ls\r']);
  });

  test('a destroyed view writes nothing, even with a ticket in hand', () => {
    const v = view('ses_a', true);
    v.open();
    const ticket = v.view.claimInput();
    v.view.destroy();
    expect(v.view.send('ls\r', ticket)).toBe(false);
    expect(v.allSent()).toEqual([]);
  });
});

describe('the url asks for exactly the role this view needs', () => {
  test('interactive=1 rides alongside observer=1 and never alone', () => {
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
      openWebSocket(
        id: string,
        path?: string,
        options?: { observer?: boolean; interactive?: boolean },
      ): unknown;
    };
    api.getToken = () => 'tok';
    api.openWebSocket('ses7', '/ws/terminal', { observer: true, interactive: true });
    api.openWebSocket('ses7', '/ws/terminal', { observer: true });
    api.openWebSocket('ses7', '/ws/terminal', { interactive: true });

    expect(opened[0]?.[0]).toBe(
      'ws://box:43202/ws/terminal?session_id=ses7&observer=1&interactive=1',
    );
    expect(opened[1]?.[0]).toBe('ws://box:43202/ws/terminal?session_id=ses7&observer=1');
    expect(opened[2]?.[0]).toBe('ws://box:43202/ws/terminal?session_id=ses7');
  });
});
