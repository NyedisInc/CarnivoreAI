import { describe, expect, test } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';
import { wrap } from './provider';

type Fn = (...a: unknown[]) => unknown;

function fakeTerm() {
  const calls: unknown[][] = [];
  const handlers: Record<string, Fn> = {};
  const sub = (name: string) => (fn: Fn) => { handlers[name] = fn; return { dispose: () => calls.push(['unsub', name]) }; };
  const term = {
    open: (el: unknown) => calls.push(['open', el]),
    write: (d: unknown, cb?: unknown) => calls.push(['write', d, cb]),
    resize: (c: number, r: number) => calls.push(['resize', c, r]),
    dispose: () => calls.push(['dispose']),
    onData: sub('data'), onResize: sub('resize'), onScroll: sub('scroll'),
    onSelectionChange: sub('selection'), onBell: sub('bell'),
  };
  return { term, calls, handlers };
}

describe('xterm provider: the interface contract', () => {
  test('attach, write, resize and dispose reach the terminal unchanged', () => {
    const { term, calls } = fakeTerm();
    const h = wrap(term);
    const el = {};
    const cb = () => {};
    h.attach(el as HTMLElement);
    h.write('abc', cb);
    h.resize(80, 24);
    h.dispose();
    expect(calls).toEqual([['open', el], ['write', 'abc', cb], ['resize', 80, 24], ['dispose']]);
  });

  test('an event subscription delivers payloads and unsubscribes', () => {
    const { term, calls, handlers } = fakeTerm();
    const got: unknown[] = [];
    const off = wrap(term).on('data', (d: unknown) => got.push(d));
    handlers.data?.('x');
    off.dispose();
    expect(got).toEqual(['x']);
    expect(calls).toEqual([['unsub', 'data']]);
  });

  test('one terminal has one handle, and a missing terminal is an inert handle', () => {
    const { term } = fakeTerm();
    expect(wrap(term)).toBe(wrap(term));
    const none = wrap(null);
    expect(none.cellSize()).toBeUndefined();
    expect(none.mouseEventsActive()).toBe(false);
    expect(none.mouseService()).toBeUndefined();
    expect(() => { none.syncInputTextarea(); none.clearRenderer(); none.quiesceViewport(); }).not.toThrow();
  });

  test('the private reaches answer from the xterm shape and tolerate its absence', () => {
    const synced: number[] = [];
    const cleared: number[] = [];
    const viewport = { scrollBarWidth: 7, syncScrollArea: () => 1, _innerRefresh: () => 1 };
    const mouse = { getCoords: () => 0 };
    const h = wrap({
      _core: {
        _syncTextArea: () => synced.push(1), viewport, _mouseService: mouse,
        coreMouseService: { areMouseEventsActive: true },
        _renderService: { clear: () => cleared.push(1), dimensions: { css: { cell: { width: 9, height: 18 } } } },
      },
    });
    h.syncInputTextarea(); h.clearRenderer();
    expect(synced).toEqual([1]);
    expect(cleared).toEqual([1]);
    expect(h.cellSize()).toEqual({ width: 9, height: 18 });
    expect(h.scrollBarWidth()).toBe(7);
    expect(h.mouseEventsActive()).toBe(true);
    expect(h.mouseService()).toBe(mouse);
    h.quiesceViewport();
    expect(viewport.syncScrollArea()).toBeUndefined();
    expect(viewport._innerRefresh()).toBeUndefined();
    expect(() => wrap({}).scrollBarWidth()).toThrow();
  });
});

const REPO = resolve(__dirname, '../../../..');
const OWN = join('web', 'src', 'lib', 'terminal-provider') + '/';

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    if (statSync(p).isDirectory()) return n === 'node_modules' || n === 'vendor' ? [] : sources(p);
    return /\.(js|ts|svelte)$/.test(n) && !/\.test\.(ts|js)$/.test(n) ? [p] : [];
  });
}

export function coreReaches(entries: Array<[string, string]>): string[] {
  return entries.filter(([p, t]) => !p.startsWith(OWN) && /\b_core\b/.test(t)).map(([p]) => p);
}

describe('no file outside the provider reaches xterm _core', () => {
  test('the scan goes red on a seeded reach', () => {
    expect(coreReaches([['client/js/seed.js', 'var c = term._core;'], ['client/js/ok.js', 'x']])).toEqual(['client/js/seed.js']);
    expect(coreReaches([[OWN + 'provider.ts', 'term._core']])).toEqual([]);
  });

  test('the live tree is clean', () => {
    const files = [...sources(join(REPO, 'client', 'js')), ...sources(join(REPO, 'web', 'src'))];
    expect(files.length).toBeGreaterThan(200);
    const entries = files.map((f): [string, string] => [relative(REPO, f), readFileSync(f, 'utf8')]);
    expect(coreReaches(entries)).toEqual([]);
  });
});
