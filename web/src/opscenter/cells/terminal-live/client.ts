/* the bottom bar */

interface Factoryish {
  create(deps?: Record<string, unknown>): unknown;
}

interface TerminalFactory {
  createTerminalClient(
    container: HTMLElement | null,
    options: Record<string, unknown>,
  ): TerminalClient;
  PRIMARY_INPUT_OWNER: string;
  XTERM_OPTIONS: Readonly<Record<string, unknown>>;
}

export interface TerminalClient {
  init(): Promise<void>;
  reconnectToExistingSession(session: unknown, ctx?: Record<string, unknown>): Promise<void>;
  dispose(): void;
  _xtermOptionsBase?: Readonly<Record<string, unknown>> | null;
}

export interface LiveTerminal {
  client: TerminalClient;
  dispose(): void;
}

export const COLLABORATORS = [
  'TerminalScroll',
  'TerminalLayout',
  'TerminalInputBuffer',
  'AltScreenScroll',
  'TerminalStartupNotice',
  'TerminalToolsMenu',
  'TerminalSelectScrolled',
] as const;

function mod(name: string): Factoryish | null {
  const found = (globalThis as Record<string, unknown>)[name];
  if (!found || typeof (found as Factoryish).create !== 'function') return null;
  return found as Factoryish;
}

export function cellWiring(host: HTMLElement): Record<string, unknown> | null {
  const scroll = mod('TerminalScroll');
  const layout = mod('TerminalLayout');
  const buffer = mod('TerminalInputBuffer');
  const altScreen = mod('AltScreenScroll');
  const notice = mod('TerminalStartupNotice');
  const selectScrolled = mod('TerminalSelectScrolled');
  if (!scroll || !layout || !buffer || !altScreen || !notice) return null;
  const alt = altScreen.create();
  return {
    TerminalScroll: scroll.create({ altScreen: alt }),
    TerminalLayout: layout.create({ container: host }),
    TerminalInputBuffer: buffer.create(),
    AltScreenScroll: alt,
    TerminalStartupNotice: notice.create(),
    TerminalToolsMenu: null,
    TerminalSelectScrolled: selectScrolled ? selectScrolled.create() : null,
  };
}

export function startLiveTerminal(
  host: HTMLElement,
  slot: string,
  session: unknown,
): LiveTerminal | null {
  const factory = (globalThis as { CloudeTerminal?: TerminalFactory }).CloudeTerminal;
  if (!factory || typeof factory.createTerminalClient !== 'function') return null;
  const wiring = cellWiring(host);
  if (!wiring) return null;

  const client = factory.createTerminalClient(host, {
    chrome: {},
    wiring,
    sessionId: sessionIdOf(session),
    role: { primary: true },
    inputOwner: slot,
  });

  let ended = false;
  const gate = acquireAttach();
  const withHistory = gate.then(() => (ended ? session : withScrollback(session)));
  void (async () => {
    try {
      await nextPaint();
      if (ended) return;
      await client.init();
      if (ended) return;
      const bound = await withHistory;
      if (ended) return;
      await client.reconnectToExistingSession(bound);
      if (ended) return;
      const bg = (globalThis as { TerminalBackground?: { repaint(): unknown } }).TerminalBackground;
      bg?.repaint();
    } catch (err) {
      console.error('CloudeOpscenter: a terminal cell failed to attach', err);
    } finally {
      void gate.then(releaseAttach);
    }
    if (ended) client.dispose();
  })();

  return {
    client,
    dispose(): void {
      ended = true;
      client.dispose();
    },
  };
}

export const PAINT_WAIT_MS = 50;

export function nextPaint(): Promise<void> {
  return new Promise<void>((resolve) => {
    let done = false;
    const run = (): void => {
      if (done) return;
      done = true;
      resolve();
    };
    setTimeout(run, PAINT_WAIT_MS);
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => setTimeout(run, 0));
  });
}

export const ATTACH_CONCURRENCY = 6;

let attaching = 0;
const queued: (() => void)[] = [];

function acquireAttach(): Promise<void> {
  if (attaching < ATTACH_CONCURRENCY) {
    attaching += 1;
    return Promise.resolve();
  }
  return new Promise<void>((resolve) => queued.push(resolve));
}

function releaseAttach(): void {
  const next = queued.shift();
  if (next) next();
  else attaching -= 1;
}

export const SCROLLBACK_WAIT_MS = 4000;

interface SessionApi {
  getSession(id: string, opts: Record<string, unknown>): Promise<unknown>;
}

export async function withScrollback(session: unknown): Promise<unknown> {
  const api = (globalThis as { API?: Partial<SessionApi> }).API;
  const id = sessionIdOf(session);
  if (!id || !api || typeof api.getSession !== 'function') return session;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const late = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), SCROLLBACK_WAIT_MS);
  });
  try {
    const info = (await Promise.race([
      api.getSession(id, {
        includeScrollback: true,
        scrollbackLines: (globalThis as { CloudeTerminal?: { SCROLLBACK_ROWS?: number } }).CloudeTerminal?.SCROLLBACK_ROWS,
      }),
      late,
    ])) as { initial_scrollback_b64?: string | null } | null;
    const b64 = info?.initial_scrollback_b64;
    if (!b64) return session;
    return { ...(session as Record<string, unknown>), initial_scrollback_b64: b64 };
  } catch (err) {
    console.warn('CloudeOpscenter: a terminal cell attached without its history', err);
    return session;
  } finally {
    clearTimeout(timer);
  }
}

function sessionIdOf(session: unknown): string {
  const wrapper = session as { session?: { id?: string }; id?: string } | null;
  return (wrapper?.session?.id ?? wrapper?.id ?? '').trim();
}
