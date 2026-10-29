/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, tick } from 'svelte';

vi.mock('../../opscenter/api', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  const { fakePins } = await import('../session-rail/test-support.svelte');
  return { ...real, sessions: fakePins.sessions, primarySessionId: () => 'ses_1' };
});
vi.mock('../../opscenter/api/asleep.svelte', async () => {
  const { fakePins } = await import('../session-rail/test-support.svelte');
  return { asleep: fakePins.asleep };
});
vi.mock('../../opscenter/api/recent.svelte', async () => {
  const { fakePins } = await import('../session-rail/test-support.svelte');
  return { recent: fakePins.recent };
});
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { ScopeProbe } = await import('../session-rail/test-support.svelte');
  return { entryFor: () => ({ component: ScopeProbe }) };
});

import { RAIL_FIELD } from '../session-rail/rail-model';
import { openKey } from '../session-rail/rail-open';
import { railSlideout } from '../session-rail/slideout.svelte';
import { BOTTOM_FIELD, follow, keyIn, mountRails, unmountRails } from '../session-rail/rail-test-harness';
import { fakeActive, fakePins } from '../session-rail/test-support.svelte';
import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import { panelPins, pinKey } from './panel-pins.svelte';
import { nameLetters, pinnedAgentFor } from './pinned-scope';

const row = (id: number, name: string, session: string, extra: Record<string, unknown> = {}): unknown => ({
  session_row_id: id, project_id: id, label: name, activity_status: 'idle', session: { id: session, working_dir: `/w/${name}` }, ...extra,
});
const probe = (): string | undefined => document.querySelector<HTMLElement>('[data-rail-edge="side"] [data-probe]')?.dataset['scope'];
const label = (): string | undefined => document.querySelector<HTMLElement>('[data-session-rail][data-rail-edge="side"] [data-zone-item="core.notes"]')?.getAttribute('aria-label')?.split(', ').slice(1).join(', ') || undefined;
const badges = (): string[] => [...document.querySelectorAll<HTMLElement>('[data-pinned-key-badge]')].map((b) => b.textContent ?? '');
const grip = (): HTMLElement => document.querySelector<HTMLElement>('[data-rail-grip="side"]')!;
const pinNow = (): void => {
  grip().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
  flushSync();
};

beforeEach(() => {
  localStorage.clear();
  fakeActive.id = 'ses_1';
  fakePins.sessions.status = 'ok';
  fakePins.asleep.status = 'ok';
  fakePins.recent.status = 'ok';
  fakePins.recent.data = { state: 'ok', sessions: [] };
  fakePins.sessions.data = [row(7, 'api', 'ses_1'), row(8, 'docs', 'ses_2')];
  fakePins.asleep.data = [];
  panelPins.reload();
  mountRails();
  follow(RAIL_FIELD, { v: 1, items: [{ widget: 'core.files' }, { widget: 'core.notes' }] });
  follow(BOTTOM_FIELD, { v: 1, items: [{ widget: 'core.notes' }] });
  keyIn('side', 'core.notes').click();
  flushSync();
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  railSlideout.close();
  unmountRails();
});

describe('the pin store', () => {
  test('round trips by row id per browser, and a throwing storage never throws', () => {
    panelPins.pin('side', 'core.notes', 7);
    expect(localStorage.getItem(pinKey('side'))).toBe('{"tabs":{"core.notes":7}}');
    panelPins.reload();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    localStorage.setItem(pinKey('bottom'), '{"row":"ses_1"}');
    panelPins.reload();
    expect(panelPins.pinnedRow('bottom', 'core.notes')).toBeNull();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(() => panelPins.reload()).not.toThrow();
    expect(() => panelPins.pin('bottom', 'core.notes', 9)).not.toThrow();
    expect(panelPins.pinnedRow('bottom', 'core.notes')).toBe(9);
  });
});

describe('the lock is per tab (issue #1631)', () => {
  test('a stored lock belongs to one placement key: a sibling tab of the same section is not locked', () => {
    panelPins.pin('side', 'core.notes', 7);
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(panelPins.pinnedRow('side', 'core.files')).toBeNull();
    expect(panelPins.pinned('side', 'core.files')).toBe(false);
    expect(panelPins.pinned('side')).toBe(true);
    panelPins.unpin('side', 'core.files');
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    panelPins.unpin('side', 'core.notes');
    expect(localStorage.getItem(pinKey('side'))).toBeNull();
  });

  test('an old per-section lock is read, then moved onto the tab its section shows, once, and the new shape is written', () => {
    localStorage.setItem(pinKey('side'), '{"rows":[7,null]}');
    panelPins.reload();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBeNull();
    expect(panelPins.adoptLegacy('side', 1, 'core.notes')).toBe(false);
    expect(panelPins.adoptLegacy('side', 0, 'core.notes')).toBe(true);
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(panelPins.pinnedRow('side', 'core.files')).toBeNull();
    expect(localStorage.getItem(pinKey('side'))).toBe('{"tabs":{"core.notes":7}}');
    expect(panelPins.adoptLegacy('side', 0, 'core.files')).toBe(false);
  });

  test('the very first shape, one lock for the whole edge, moves onto the tab each section shows', () => {
    localStorage.setItem(pinKey('bottom'), '{"row":8}');
    panelPins.reload();
    panelPins.adoptLegacy('bottom', 0, 'core.files');
    expect(localStorage.getItem(pinKey('bottom'))).toBe('{"tabs":{"core.files":8},"rows":[null,8]}');
    panelPins.adoptLegacy('bottom', 1, 'core.notes');
    expect(panelPins.pinnedRow('bottom', 'core.notes')).toBe(8);
    expect(localStorage.getItem(pinKey('bottom'))).toBe('{"tabs":{"core.files":8,"core.notes":8}}');
  });

  test('the rail moves an old lock onto its active tab when it draws, and the sibling tab stays unlocked', () => {
    railSlideout.close();
    localStorage.setItem(pinKey('side'), '{"rows":[7,null]}');
    panelPins.reload();
    localStorage.setItem(openKey('side'), '["core.notes"]');
    railSlideout.reload();
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(panelPins.pinnedRow('side', 'core.files')).toBeNull();
    expect(probe()).toBe('ses_1:7');
  });
});

describe('a pin is the accent bar, never an outline or a lock icon (issue #1731)', () => {
  const lit = (edge: string): HTMLElement[] => [...document.querySelectorAll<HTMLElement>(`[data-rail-grip="${edge}"] [data-rail-pin-section]`)];
  test('only a pinned section lights its stretch of the edge line, and no lock frame or lock icon exists', () => {
    expect(lit('side')).toHaveLength(0);
    pinNow();
    expect(lit('side')).toHaveLength(1);
    expect(document.querySelector('[data-lock-frame], [data-key-lock], [data-lock-title]')).toBeNull();
    pinNow();
    expect(lit('side')).toHaveLength(0);
  });
  test('a split side rail lights only the section showing the locked tab', async () => {
    pinNow();
    follow(RAIL_FIELD, { v: 2, ratio: 0.5, sections: [{ items: [{ widget: 'core.files' }] }, { items: [{ widget: 'core.notes' }] }] });
    await tick();
    expect(lit('side').map((f) => f.dataset['railPinSection'])).toEqual(['1']);
  });
});

describe('a pinned panel keeps its agent', () => {
  test('the widget gets the pinned row scope while the active session moves on, and unpinning follows again', () => {
    expect(probe()).toBe('ses_1:7');
    pinNow();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(label()).toBe('pinned on api');
    fakeActive.id = 'ses_2';
    flushSync();
    expect(probe()).toBe('ses_1:7');
    expect(label()).toBe('pinned on api');
    pinNow();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBeNull();
    expect(probe()).toBe('ses_2:8');
    expect(label()).toBeUndefined();
  });

  test('a rename shows at once, and an asleep agent keeps the pin with its state word', () => {
    pinNow();
    fakePins.sessions.data = [row(7, 'api2', 'ses_1'), row(8, 'docs', 'ses_2')];
    flushSync();
    expect(label()).toBe('pinned on api2');
    fakePins.sessions.data = [row(8, 'docs', 'ses_2')];
    fakePins.asleep.data = [{ id: 7, session_uuid: 'u-7', title: 'api2', working_dir: '/w/api2', project_id: 7 }];
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(railSlideout.shown('side')).toEqual(['core.notes']);
    expect(label()).toBe('pinned on api2, asleep');
    expect(probe()).toBe('u-7:7');
  });

  test('an agent absent from a COMPLETE read unpins and closes once; an unreadable listing changes nothing', () => {
    vi.useFakeTimers();
    const say = vi.spyOn(terminalLayout, 'announce');
    pinNow();
    say.mockClear();
    fakePins.sessions.status = 'error';
    fakePins.sessions.data = [row(8, 'docs', 'ses_2')];
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(railSlideout.shown('side')).toEqual(['core.notes']);
    fakePins.sessions.status = 'ok';
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    vi.advanceTimersByTime(2100);
    expect(panelPins.pinnedRow('side', 'core.notes')).toBeNull();
    expect(railSlideout.shown('side')).toEqual([]);
    expect(say.mock.calls.filter(([line]) => line === 'notes closed, its agent is gone')).toHaveLength(1);
    expect(pinnedAgentFor(7, null, null, null, true).state).toBe('unknown');
  });
});

describe('a one tick absence', () => {
  test('keeps the pin when the row reappears inside the settle (the held absence is the two tests above)', () => {
    vi.useFakeTimers();
    pinNow();
    fakePins.sessions.data = [row(8, 'docs', 'ses_2')];
    flushSync();
    vi.advanceTimersByTime(900);
    fakePins.sessions.data = [row(7, 'api', 'ses_1'), row(8, 'docs', 'ses_2')];
    flushSync();
    vi.advanceTimersByTime(5000);
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(railSlideout.shown('side')).toEqual(['core.notes']);
  });
});

describe('a pinned panel never shows another agent while its own is unresolved', () => {
  test('a not yet loaded listing holds the body instead of following the active session, and the agent returns when it loads', () => {
    pinNow();
    expect(probe()).toBe('ses_1:7');
    fakeActive.id = 'ses_2';
    fakePins.sessions.data = null;
    fakePins.sessions.status = 'loading';
    flushSync();
    expect(probe()).toBeUndefined();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(railSlideout.shown('side')).toEqual(['core.notes']);
    fakePins.sessions.data = [row(7, 'api', 'ses_1'), row(8, 'docs', 'ses_2')];
    fakePins.sessions.status = 'ok';
    flushSync();
    expect(probe()).toBe('ses_1:7');
  });

  test('a stored row that is neither listed nor asleep (a reopen offer) keeps the pin as stopped; only an absence from all three reads drops it', () => {
    vi.useFakeTimers();
    pinNow();
    fakePins.sessions.data = [row(8, 'docs', 'ses_2')];
    fakePins.recent.data = { state: 'ok', sessions: [{ id: 7, session_uuid: 'u-7', title: 'api', working_dir: '/w/api', project_id: 7 }] };
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    expect(label()).toBe('pinned on api, stopped');
    fakePins.recent.data = { state: 'probe_unavailable', sessions: [] };
    flushSync();
    expect(panelPins.pinnedRow('side', 'core.notes')).toBe(7);
    fakePins.recent.data = { state: 'ok', sessions: [] };
    flushSync();
    vi.advanceTimersByTime(2100);
    expect(panelPins.pinnedRow('side', 'core.notes')).toBeNull();
  });
});

describe('the pinned key badge', () => {
  test('nameLetters', () => {
    const cases: [string, string][] = [['bot-Misc UI', 'M'], ['bot-Fixes', 'F'], ['carnivore console', 'C'], ['api', 'A'], ['build agent', 'B'], ['Cv-', 'C'], ['', ''], ['--', '']];
    for (const [name, letter] of cases) expect(nameLetters(name)[0] ?? '', name).toBe(letter);
  });

  test('a locked tab always wears its agent letter, the active agent included, and only that tab', () => {
    expect(badges()).toEqual([]);
    pinNow();
    expect(badges()).toEqual(['A']);
    fakeActive.id = 'ses_2';
    flushSync();
    expect(badges()).toEqual(['A']);
    expect(keyIn('side', 'core.notes').getAttribute('aria-label')).toBe('notes, pinned on api');
    expect(keyIn('side', 'core.files').querySelector('[data-pinned-key-badge]')).toBeNull();
    expect(keyIn('bottom', 'core.notes').querySelector('[data-pinned-key-badge]')).toBeNull();
    fakeActive.id = 'ses_unlisted';
    flushSync();
    expect(badges()).toEqual(['A']);
    fakeActive.id = 'ses_1';
    flushSync();
    expect(badges()).toEqual(['A']);
  });
});
