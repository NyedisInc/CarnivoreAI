/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { tabVisibility, type VisibilityInput } from './zone-visibility';
import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';
import ZoneHarness from './fixtures/ZoneHarness.svelte';
import { resetWorld, world } from './fixtures/world.svelte';

const BASE: VisibilityInput = { unseen: false, panel: 'open', active: true, docHidden: false, onScreen: true };

describe('tabVisibility', () => {
  const cases: [string, Partial<VisibilityInput>, string][] = [
    ['active, open, seen, on screen', {}, 'shown'],
    ['not the active tab', { active: false }, 'hidden'],
    ['the document is hidden', { docHidden: true }, 'hidden'],
    ['off screen', { onScreen: false }, 'hidden'],
    ['panel collapsed (glance)', { panel: 'collapsed' }, 'parked'],
    ['panel closed', { panel: 'closed' }, 'parked'],
    ['a closed key mount', { unseen: true }, 'parked'],
    ['closed key mount outranks everything', { unseen: true, active: false, docHidden: true }, 'parked'],
    ['closed panel outranks an inactive tab', { panel: 'closed', active: false }, 'parked'],
  ];
  test.each(cases)('%s is %s', (_name, change, want) => {
    expect(tabVisibility({ ...BASE, ...change })).toBe(want);
  });
});

class FakeObserver {
  static all: FakeObserver[] = [];
  targets = new Set<Element>();
  constructor(private callback: IntersectionObserverCallback) {
    FakeObserver.all.push(this);
  }
  observe(el: Element): void { this.targets.add(el); }
  unobserve(el: Element): void { this.targets.delete(el); }
  disconnect(): void { this.targets.clear(); }
  report(el: Element, isIntersecting: boolean): void {
    this.callback([{ target: el, isIntersecting } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
  }
}

let handle: ReturnType<typeof mount> | null = null;
const visibleOf = (tab: string): string | undefined => document.querySelector<HTMLElement>(`[data-stub="${tab}"]`)?.dataset['paneVisible'];
const toolOf = (): string[] => [...document.querySelectorAll('[data-zone-toolbar] [data-tool]')].map((el) => el.textContent ?? '');

function draw(mode: 'all' | 'active' = 'all'): void {
  resetWorld();
  handle = mount(ZoneHarness, { target: document.body, props: { mode } });
  flushSync();
}

beforeEach(() => {
  vi.stubGlobal('VisibilityObserver', FakeObserver);
});

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('a zone with two widget tabs', () => {
  test('the toolbar is the active tab\'s and switches with it', () => {
    draw();
    expect(toolOf()).toEqual(['tool a']);
    world.active = 'b';
    flushSync();
    expect(toolOf()).toEqual(['tool b']);
  });

  test('each tab declares on its own <zone>#<tab> key and the two never overwrite each other', () => {
    draw();
    expect(declaredActionsFor('test:zone#a').map((one) => one.id)).toEqual(['act-a']);
    expect(declaredActionsFor('test:zone#b').map((one) => one.id)).toEqual(['act-b']);
    expect(document.querySelector('[data-stub="b"]')?.getAttribute('data-host')).toBe('test:zone#b');
  });

  test('every tab stays mounted, the inactive one inert and hidden from readers', () => {
    draw();
    const b = document.querySelector<HTMLElement>('[data-zone-pane="b"]')!;
    expect((b as HTMLElement & { inert?: boolean }).inert).toBe(true);
    expect(b.getAttribute('aria-hidden')).toBe('true');
    expect((document.querySelector('[data-zone-pane="a"]') as HTMLElement & { inert?: boolean }).inert).toBe(false);
  });

  test('mount "active" draws only the active tab', () => {
    draw('active');
    expect(document.querySelector('[data-stub="a"]')).not.toBeNull();
    expect(document.querySelector('[data-stub="b"]')).toBeNull();
    world.active = 'b';
    flushSync();
    expect(document.querySelector('[data-stub="a"]')).toBeNull();
    expect(document.querySelector('[data-stub="b"]')).not.toBeNull();
  });

  test('a tab that leaves and returns starts with empty header slots', () => {
    draw('active');
    world.active = 'b';
    flushSync();
    world.active = 'a';
    flushSync();
    expect(toolOf()).toEqual(['tool a']);
    expect(declaredActionsFor('test:zone#a')).toHaveLength(1);
  });
});

describe('the visibility rune on the pane and in useWidget', () => {
  test('shown while active and open; hidden when another tab is active; parked while the panel is closed; shown again on restore', () => {
    draw();
    expect(visibleOf('a')).toBe('shown');
    expect(visibleOf('b')).toBe('hidden');
    world.active = 'b';
    flushSync();
    expect(visibleOf('a')).toBe('hidden');
    expect(visibleOf('b')).toBe('shown');
    world.panel = 'closed';
    flushSync();
    expect(visibleOf('a')).toBe('parked');
    expect(visibleOf('b')).toBe('parked');
    world.panel = 'collapsed';
    flushSync();
    expect(visibleOf('b')).toBe('parked');
    world.panel = 'open';
    flushSync();
    expect(visibleOf('b')).toBe('shown');
  });

  test('useWidget reads the same rune, and says shown outside any zone', () => {
    draw();
    expect(document.querySelector('[data-stub="a"]')?.getAttribute('data-widget-visible')).toBe('shown');
    world.panel = 'closed';
    flushSync();
    expect(document.querySelector('[data-stub="a"]')?.getAttribute('data-widget-visible')).toBe('parked');
    unmount(handle!);
    document.body.innerHTML = '';
    handle = null;
  });

  test('a hidden document makes the shown tab hidden, with no frame wait, and the return makes it shown', () => {
    const raf = vi.fn();
    vi.stubGlobal('requestAnimationFrame', raf);
    draw();
    const state = vi.spyOn(document, 'visibilityState', 'get');
    state.mockReturnValue('hidden');
    document.dispatchEvent(new Event('visibilitychange'));
    flushSync();
    expect(visibleOf('a')).toBe('hidden');
    state.mockReturnValue('visible');
    document.dispatchEvent(new Event('visibilitychange'));
    flushSync();
    expect(visibleOf('a')).toBe('shown');
    expect(raf).not.toHaveBeenCalled();
  });

  test('a pane the shared observer reports off screen is hidden, and back in view is shown; an unobserved pane starts shown', () => {
    draw();
    const pane = document.querySelector('[data-zone-pane="a"]')!;
    expect(visibleOf('a')).toBe('shown');
    const observer = FakeObserver.all[0]!;
    expect(observer.targets.has(pane)).toBe(true);
    observer.report(pane, false);
    flushSync();
    expect(visibleOf('a')).toBe('hidden');
    observer.report(pane, true);
    flushSync();
    expect(visibleOf('a')).toBe('shown');
  });
});
