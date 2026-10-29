
export interface ViewerTerminal {
  resize(cols: number, rows: number): void;
  write(data: Uint8Array | string): void;
  dispose(): void;
}

export interface ViewerSocketLike {
  binaryType: string;
  close(code?: number, reason?: string): void;
  send?(data: Uint8Array | string): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}

export type ViewerState = 'connecting' | 'live' | 'reconnecting' | 'gone' | 'closed';

interface WriteQueueHelpers {
  MAX_QUEUED_BYTES: number;
  dropMarker(bytes: number): string;
  overflowBytes(queuedBytes: number, incomingBytes: number, budget?: number): number;
  shedFront(queue: Array<{ length: number }>, needed: number): number;
}

export interface ViewerSocketDeps {
  openSocket(sessionId: string, interactive: boolean): ViewerSocketLike;
  backoffMs(attempt: number): number;
  requestFrame(callback: () => void): number;
  cancelFrame(handle: number): void;
  setTimer(callback: () => void, ms: number): number;
  clearTimer(handle: number): void;
  queue: WriteQueueHelpers;
}

export interface ViewerSocketOptions {
  sessionId: string;
  interactive?: boolean;
  term: ViewerTerminal;
  onState?: (state: ViewerState) => void;
  onGrid?: (cols: number, rows: number) => void;
  deps?: Partial<ViewerSocketDeps>;
}

export interface InputTicket {
  readonly session: string;
  readonly connection: number;
}

export interface ViewerSocket {
  readonly state: ViewerState;
  readonly interactive: boolean;
  start(): void;
  claimInput(): InputTicket;
  send(data: string, ticket: InputTicket): boolean;
  destroy(): void;
}

export const FLUSH_BACKSTOP_MS = 20;

export const CLOSE_UNKNOWN_SESSION = 4404;

export const CLOSE_OVERFLOW = 4429;

interface ApiGlobal {
  openWebSocket(
    sessionId: string | null,
    path?: string,
    options?: { observer?: boolean; interactive?: boolean },
  ): ViewerSocketLike;
}

function pageDeps(): Partial<ViewerSocketDeps> | null {
  const api = (globalThis as { API?: ApiGlobal }).API;
  const queue = (globalThis as { TerminalWriteQueue?: WriteQueueHelpers }).TerminalWriteQueue;
  const policy = (globalThis as { TerminalReconnectPolicy?: { backoffMs(n: number): number } })
    .TerminalReconnectPolicy;
  if (!queue || !policy) return null;
  return {
    ...(api && typeof api.openWebSocket === 'function'
      ? {
          openSocket: (sessionId: string, interactive: boolean) =>
            api.openWebSocket(sessionId, '/ws/terminal', { observer: true, interactive }),
        }
      : {}),
    backoffMs: (attempt: number) => policy.backoffMs(attempt),
    requestFrame: (callback: () => void) => globalThis.requestAnimationFrame(callback),
    cancelFrame: (handle: number) => globalThis.cancelAnimationFrame(handle),
    setTimer: (callback: () => void, ms: number) =>
      globalThis.setTimeout(callback, ms) as unknown as number,
    clearTimer: (handle: number) => globalThis.clearTimeout(handle),
    queue,
  };
}

function asBytes(data: unknown): Uint8Array | null {
  if (data instanceof Uint8Array) return data;
  if (data instanceof ArrayBuffer) return new Uint8Array(data);
  return null;
}

export function createViewerSocket(options: ViewerSocketOptions): ViewerSocket {
  const defaults = pageDeps();
  const deps = { ...(defaults ?? {}), ...(options.deps ?? {}) } as ViewerSocketDeps;

  const ready =
    !!deps &&
    typeof deps.openSocket === 'function' &&
    typeof deps.backoffMs === 'function' &&
    typeof deps.requestFrame === 'function' &&
    typeof deps.cancelFrame === 'function' &&
    typeof deps.setTimer === 'function' &&
    typeof deps.clearTimer === 'function' &&
    !!deps.queue;

  let state: ViewerState = 'connecting';
  let socket: ViewerSocketLike | null = null;
  let destroyed = false;
  let started = false;
  const interactive = options.interactive === true;

  let connection = 0;
  let socketOpen = false;

  let pending: Uint8Array[] = [];
  let pendingBytes = 0;
  let frame: number | null = null;
  let backstop: number | null = null;
  let retry: number | null = null;

  let attempts = 0;
  let overflowRetried = false;

  const encoder = new TextEncoder();

  function setState(next: ViewerState): void {
    if (state === next) return;
    state = next;
    options.onState?.(next);
  }

  function disarm(): void {
    if (frame !== null && deps) {
      deps.cancelFrame(frame);
      frame = null;
    }
    if (backstop !== null && deps) {
      deps.clearTimer(backstop);
      backstop = null;
    }
  }

  function flush(): void {
    disarm();
    if (destroyed || pending.length === 0) return;
    const chunks = pending;
    pending = [];
    pendingBytes = 0;
    let total = 0;
    for (const chunk of chunks) total += chunk.length;
    const merged = new Uint8Array(total);
    let at = 0;
    for (const chunk of chunks) {
      merged.set(chunk, at);
      at += chunk.length;
    }
    options.term.write(merged);
  }

  function arm(): void {
    if (destroyed || !deps) return;
    if (frame === null) frame = deps.requestFrame(flush);
    if (backstop === null) backstop = deps.setTimer(flush, FLUSH_BACKSTOP_MS);
  }

  function admit(bytes: Uint8Array): void {
    if (!deps) return;
    const needed = deps.queue.overflowBytes(pendingBytes, bytes.length);
    if (needed > 0) {
      const dropped = deps.queue.shedFront(pending, needed);
      pendingBytes = 0;
      for (const chunk of pending) pendingBytes += chunk.length;
      const marker = encoder.encode(deps.queue.dropMarker(dropped));
      pending.push(marker);
      pendingBytes += marker.length;
    }
    pending.push(bytes);
    pendingBytes += bytes.length;
    arm();
  }

  function handleText(raw: string): void {
    let message: { type?: unknown; cols?: unknown; rows?: unknown };
    try {
      message = JSON.parse(raw) as typeof message;
    } catch {
      return;
    }
    if (message.type === 'terminal_size') {
      const cols = typeof message.cols === 'number' ? message.cols : 0;
      const rows = typeof message.rows === 'number' ? message.rows : 0;
      if (cols > 0 && rows > 0) {
        options.term.resize(cols, rows);
        options.onGrid?.(cols, rows);
      }
      return;
    }
    if (message.type === 'terminal.ready') {
      setState('live');
    }
  }

  function connect(): void {
    if (destroyed || !deps) return;
    setState(attempts > 0 ? 'reconnecting' : 'connecting');
    connection += 1;
    socketOpen = false;
    let opened: ViewerSocketLike;
    try {
      opened = deps.openSocket(options.sessionId, interactive);
    } catch (err) {
      console.error('CloudeOpscenter: viewer socket could not be opened', err);
      scheduleRetry();
      return;
    }
    socket = opened;
    opened.binaryType = 'arraybuffer';
    opened.onopen = () => {
      if (destroyed) return;
      socketOpen = true;
      setState('live');
    };
    opened.onmessage = (event: { data: unknown }) => {
      if (destroyed) return;
      const bytes = asBytes(event.data);
      if (bytes) {
        attempts = 0;
        overflowRetried = false;
        setState('live');
        admit(bytes);
        return;
      }
      if (typeof event.data === 'string') handleText(event.data);
    };
    opened.onerror = () => {
    };
    opened.onclose = (event: { code: number }) => {
      if (destroyed) return;
      socket = null;
      socketOpen = false;
      const code = event?.code;
      if (code === CLOSE_UNKNOWN_SESSION) {
        setState('gone');
        return;
      }
      if (code === CLOSE_OVERFLOW && !overflowRetried) {
        overflowRetried = true;
        pending = [];
        pendingBytes = 0;
        disarm();
        setState('reconnecting');
        connect();
        return;
      }
      scheduleRetry();
    };
  }

  function scheduleRetry(): void {
    if (destroyed || !deps) return;
    attempts += 1;
    setState('reconnecting');
    retry = deps.setTimer(() => {
      retry = null;
      connect();
    }, deps.backoffMs(attempts));
  }

  return {
    get state() {
      return state;
    },
    get interactive() {
      return interactive;
    },

    claimInput(): InputTicket {
      return { session: options.sessionId, connection };
    },

    /* there is nothing */
    send(data: string, ticket: InputTicket): boolean {
      if (!interactive || destroyed || !socketOpen) return false;
      const open = socket;
      if (!open || typeof open.send !== 'function') return false;
      if (!ticket || ticket.connection !== connection) return false;
      if (ticket.session !== options.sessionId) return false;
      if (data === '') return true;
      try {
        open.send(encoder.encode(data));
      } catch (err) {
        console.warn('CloudeOpscenter: viewer input send threw', err);
        return false;
      }
      return true;
    },

    start(): void {
      if (started || destroyed) return;
      started = true;
      if (!ready) {
        console.error(
          'CloudeOpscenter: the terminal write queue or the api module is not on this page, the viewer did not open',
        );
        setState('closed');
        return;
      }
      connect();
    },
    destroy(): void {
      if (destroyed) return;
      destroyed = true;
      socketOpen = false;
      disarm();
      if (retry !== null && deps) {
        deps.clearTimer(retry);
        retry = null;
      }
      pending = [];
      pendingBytes = 0;
      const open = socket;
      socket = null;
      if (open) {
        open.onopen = null;
        open.onmessage = null;
        open.onclose = null;
        open.onerror = null;
        try {
          open.close();
        } catch (err) {
          console.warn('CloudeOpscenter: viewer socket close threw', err);
        }
      }
      try {
        options.term.dispose();
      } catch (err) {
        console.warn('CloudeOpscenter: viewer emulator dispose threw', err);
      }
      state = 'closed';
    },
  };
}
