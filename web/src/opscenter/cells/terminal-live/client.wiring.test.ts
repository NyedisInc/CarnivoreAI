
import { afterEach, describe, expect, test } from 'vitest';
import { COLLABORATORS, cellWiring } from './client';

const NAMES = [
  'TerminalScroll',
  'TerminalLayout',
  'TerminalInputBuffer',
  'AltScreenScroll',
  'TerminalStartupNotice',
] as const;

function stubGlobals(): Record<string, number> {
  const made: Record<string, number> = {};
  for (const name of NAMES) {
    made[name] = 0;
    (globalThis as Record<string, unknown>)[name] = {
      create(deps?: Record<string, unknown>) {
        made[name] = (made[name] ?? 0) + 1;
        return { __module: name, __n: made[name], __deps: deps ?? null };
      },
      __module: name,
      __default: true,
    };
  }
  return made;
}

afterEach(() => {
  for (const name of NAMES) delete (globalThis as Record<string, unknown>)[name];
});

describe('a terminal cell wiring record', () => {
  test('names every collaborator, and none of them is the page-level default', () => {
    stubGlobals();
    const wiring = cellWiring({} as HTMLElement);
    expect(wiring).not.toBeNull();
    for (const key of COLLABORATORS) {
      expect(Object.prototype.hasOwnProperty.call(wiring, key), `${key} is not in the record`)
        .toBe(true);
      const value = wiring![key] as { __default?: boolean } | null;
      if (value) expect(value.__default, `${key} fell through to the global`).toBeUndefined();
    }
    expect(COLLABORATORS.length).toBe(6);
  });

  test('two cells share nothing', () => {
    stubGlobals();
    const a = cellWiring({} as HTMLElement)!;
    const b = cellWiring({} as HTMLElement)!;
    for (const key of COLLABORATORS) {
      if (a[key] === null) continue;
      expect(a[key], `two cells share one ${key}`).not.toBe(b[key]);
    }
  });

  test('the scroll owner is handed THIS cell\'s alternate-screen scroller', () => {
    stubGlobals();
    const wiring = cellWiring({} as HTMLElement)!;
    const scroll = wiring.TerminalScroll as { __deps: { altScreen: unknown } };
    expect(scroll.__deps.altScreen).toBe(wiring.AltScreenScroll);
  });

  test('the layout pipeline is scoped to THIS cell\'s host element', () => {
    stubGlobals();
    const host = { id: 'the-cell-host' } as unknown as HTMLElement;
    const wiring = cellWiring(host)!;
    const layout = wiring.TerminalLayout as { __deps: { container: unknown } };
    expect(layout.__deps.container).toBe(host);
  });

  test('the tools menu is an explicit null, which is not the same as absent', () => {
    stubGlobals();
    const wiring = cellWiring({} as HTMLElement)!;
    expect('TerminalToolsMenu' in wiring).toBe(true);
    expect(wiring.TerminalToolsMenu).toBeNull();
  });

  test('a page without the classic tree gets no wiring at all', () => {
    expect(cellWiring({} as HTMLElement)).toBeNull();
  });
});
