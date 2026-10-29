
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { PAINT_WAIT_MS, SCROLLBACK_WAIT_MS, startLiveTerminal } from './client';

const COLLABORATOR_GLOBALS = [
  'TerminalScroll',
  'TerminalLayout',
  'TerminalInputBuffer',
  'AltScreenScroll',
  'TerminalStartupNotice',
] as const;

const ROW = { session: { id: 'ses_1' }, label: 'work', tmux_session: 'cloude_work' };

let calls: string[];
let attached: Array<Record<string, unknown>>;

function install(getSession: (id: string, opts: Record<string, unknown>) => Promise<unknown>): void {
  const g = globalThis as Record<string, unknown>;
  for (const name of COLLABORATOR_GLOBALS) g[name] = { create: () => ({ name }) };
  g.CloudeTerminal = {
    PRIMARY_INPUT_OWNER: 'primary',
    XTERM_OPTIONS: {},
    createTerminalClient: () => ({
      init: async () => {
        calls.push('init');
      },
      reconnectToExistingSession: async (session: Record<string, unknown>) => {
        calls.push('attach');
        attached.push(session);
      },
      dispose: () => {
        calls.push('dispose');
      },
    }),
  };
  g.API = {
    getSession: (id: string, opts: Record<string, unknown>) => {
      calls.push('getSession');
      return getSession(id, opts);
    },
  };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) await Promise.resolve();
  if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(PAINT_WAIT_MS);
  else await new Promise((resolve) => setTimeout(resolve, PAINT_WAIT_MS + 5));
  for (let i = 0; i < 20; i++) await Promise.resolve();
}

beforeEach(() => {
  calls = [];
  attached = [];
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  const g = globalThis as Record<string, unknown>;
  for (const name of [...COLLABORATOR_GLOBALS, 'CloudeTerminal', 'API']) delete g[name];
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('a terminal cell attach', () => {
  test('asks for the scrollback and hands it to the attach, which paints it before the socket', async () => {
    const seen: Array<[string, Record<string, unknown>]> = [];
    install(async (id, opts) => {
      seen.push([id, opts]);
      return { session: { id }, initial_scrollback_b64: 'SElTVE9SWQ==' };
    });
    const live = startLiveTerminal({} as HTMLElement, 'terminal:ses_1', ROW);
    expect(live).not.toBeNull();
    await settle();

    expect(seen).toEqual([['ses_1', { includeScrollback: true }]]);
    expect(seen[0]![1]).not.toHaveProperty('cols');
    expect(seen[0]![1]).not.toHaveProperty('rows');
    expect(calls.indexOf('getSession')).toBeLessThan(calls.indexOf('attach'));
    expect(attached).toHaveLength(1);
    expect(attached[0]!.initial_scrollback_b64).toBe('SElTVE9SWQ==');
    expect(attached[0]!.label).toBe('work');
    expect(attached[0]!.tmux_session).toBe('cloude_work');
    live!.dispose();
  });

  test('a failed fetch still attaches live, from the row as given', async () => {
    install(async () => {
      throw new Error('500');
    });
    const live = startLiveTerminal({} as HTMLElement, 'terminal:ses_1', ROW);
    await settle();
    expect(attached).toEqual([ROW]);
    live!.dispose();
  });

  test('a fetch that never answers still attaches live once the wait runs out', async () => {
    vi.useFakeTimers();
    install(() => new Promise(() => {}));
    const live = startLiveTerminal({} as HTMLElement, 'terminal:ses_1', ROW);
    await settle();
    expect(attached).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(SCROLLBACK_WAIT_MS);
    await settle();
    expect(attached).toEqual([ROW]);
    live!.dispose();
  });

  test('a capture landing after the cell was torn down opens nothing', async () => {
    let answer: (value: unknown) => void = () => {};
    install(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    const live = startLiveTerminal({} as HTMLElement, 'terminal:ses_1', ROW);
    await settle();
    live!.dispose();
    answer({ session: { id: 'ses_1' }, initial_scrollback_b64: 'U1RBTEU=' });
    await settle();
    expect(attached).toHaveLength(0);
    expect(calls).not.toContain('attach');
  });
});
