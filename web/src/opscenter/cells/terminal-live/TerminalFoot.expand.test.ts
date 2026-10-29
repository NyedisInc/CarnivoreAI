/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';
import { sessionUsageLabels } from '../../api';
import type { AccountUsage, SessionTokenUsage } from '../../api/types';
import { FOOT_EXPANDED_KEY } from './foot-expand';

let currentPayload: SessionTokenUsage | null = null;
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessionUsage: vi.fn(() => ({ data: currentPayload, status: 'ok' })),
    releaseSessionUsage: vi.fn(),
  };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  currentPayload = null;
  try { localStorage.clear(); } catch {  }
  vi.restoreAllMocks();
});

const FAR_RESET = new Date(Date.now() + 3 * 24 * 3600 * 1000).toISOString();

function account(overrides: Partial<AccountUsage> = {}): AccountUsage {
  return {
    id: 'acct-1',
    name: 'Claude Code - Studio',
    short_name: 'Studio',
    provider: 'claude',
    plan: null,
    identity: null,
    credential_state: 'ok',
    fetched_at: null,
    next_poll_at: null,
    error: null,
    windows: [
      { kind: 'five_hour', label: '5h', used_pct: 41, resets_at: FAR_RESET },
      { kind: 'seven_day', label: '7d', used_pct: 12, resets_at: FAR_RESET },
    ],
    color: null,
    managed: false,
    ...overrides,
  } as AccountUsage;
}

function usage(overrides: Partial<SessionTokenUsage> = {}): SessionTokenUsage {
  return {
    state: 'ok',
    family: 'claude',
    model: 'claude-opus-4',
    model_display_name: 'Opus 4',
    model_cost_tier: 3,
    effort: 'high',
    input_tokens: 12000,
    output_tokens: 3400,
    cache_read_input_tokens: null,
    cache_creation_input_tokens: null,
    total_tokens: 15400,
    cost_estimate_usd: 1.2345,
    context_used_tokens: 447000,
    context_window_tokens: 1000000,
    context_remaining_pct: 55.3,
    as_of: '2026-09-24T00:00:00Z',
    detail: null,
    account: account(),
    ...overrides,
  };
}

function setup(payload: SessionTokenUsage | null, width = 390): HTMLElement {
  currentPayload = payload;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width } }));
  flushSync();
  return target;
}

function toggle(target: HTMLElement): HTMLButtonElement {
  const button = target.querySelector<HTMLButtonElement>('button.oc-tf');
  if (!button) throw new Error('no foot bar button');
  return button;
}

function region(target: HTMLElement): HTMLElement | null {
  const id = toggle(target).getAttribute('aria-controls');
  return id ? document.getElementById(id) : null;
}

function stats(target: HTMLElement): HTMLElement | null {
  return region(target)?.querySelector<HTMLElement>('.oc-tfs') ?? null;
}

test('the bar is a button, collapsed by default, whose aria-controls names the grown bar', () => {
  const target = setup(usage());
  const button = toggle(target);
  expect(button.getAttribute('type')).toBe('button');
  expect(button.getAttribute('aria-expanded')).toBe('false');
  const grown = region(target);
  expect(grown).not.toBeNull();
  expect(grown?.hidden).toBe(true);
});

test('a click expands, a second click collapses, and aria-expanded follows', () => {
  const target = setup(usage());
  const button = toggle(target);
  button.click();
  flushSync();
  expect(button.getAttribute('aria-expanded')).toBe('true');
  expect(region(target)?.hidden).toBe(false);
  button.click();
  flushSync();
  expect(button.getAttribute('aria-expanded')).toBe('false');
  expect(region(target)?.hidden).toBe(true);
});

test('clicking the grown stats half collapses it', () => {
  const target = setup(usage());
  toggle(target).click();
  flushSync();
  stats(target)?.click();
  flushSync();
  expect(toggle(target).getAttribute('aria-expanded')).toBe('false');
});

test('Escape inside the bar collapses it', () => {
  const target = setup(usage());
  const button = toggle(target);
  button.click();
  flushSync();
  button.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(button.getAttribute('aria-expanded')).toBe('false');
});

test('Escape typed OUTSIDE the bar is left alone, because the terminal owns that key', () => {
  const target = setup(usage());
  toggle(target).click();
  flushSync();
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  flushSync();
  expect(toggle(target).getAttribute('aria-expanded')).toBe('true');
});

test('a pointerdown outside the bar collapses it; one inside does not', () => {
  const target = setup(usage());
  toggle(target).click();
  flushSync();
  region(target)?.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  flushSync();
  expect(toggle(target).getAttribute('aria-expanded')).toBe('true');
  const elsewhere = document.createElement('div');
  document.body.append(elsewhere);
  elsewhere.dispatchEvent(new Event('pointerdown', { bubbles: true }));
  flushSync();
  expect(toggle(target).getAttribute('aria-expanded')).toBe('false');
});

test('the choice is remembered per device and read back on the next mount', () => {
  const first = setup(usage());
  toggle(first).click();
  flushSync();
  expect(localStorage.getItem(FOOT_EXPANDED_KEY)).toBe('1');
  const second = setup(usage());
  expect(toggle(second).getAttribute('aria-expanded')).toBe('true');
  toggle(second).click();
  flushSync();
  expect(localStorage.getItem(FOOT_EXPANDED_KEY)).toBe('0');
});

test('storage that throws never breaks the toggle', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied'); });
  const target = setup(usage());
  expect(toggle(target).getAttribute('aria-expanded')).toBe('false');
  toggle(target).click();
  flushSync();
  expect(toggle(target).getAttribute('aria-expanded')).toBe('true');
});

test('PARITY: the grown bar shows every figure the drawer panel\'s full view is built from', () => {
  const payload = usage();
  const target = setup(payload, 390);
  toggle(target).click();
  flushSync();
  const grown = region(target);
  const text = grown?.textContent ?? '';
  const model = sessionUsageLabels(payload, null);
  if (model.state !== 'ok') throw new Error('fixture must be ok');
  for (const row of model.rows) {
    if (row.key === 'model') {
      expect(text).toContain(row.spans?.[0]?.text ?? '');
      expect(text).toContain(row.spans?.[2]?.text ?? '');
    } else {
      expect(text).toContain(row.label);
      expect(text).toContain(row.text);
    }
  }
  expect(text).toContain(model.context.percentText);
  expect(text).toContain(model.context.compactDetail);
  expect(grown?.querySelector(`[title="${model.context.detail}"]`)).toBeNull();
  expect(model.windows.length).toBe(2);
  for (const w of model.windows) {
    expect(text).toContain(w.label);
    expect(text).toContain(w.percentText);
    expect(text).toContain(w.resetDuration);
    expect(text).not.toContain('reset in');
  }
});

test('the grown stats are a labeled grid: one label and one value per figure, three meters', () => {
  const target = setup(usage(), 390);
  toggle(target).click();
  flushSync();
  const grown = stats(target);
  expect(grown?.getAttribute('data-usage-state')).toBe('ok');
  const items = [...(grown?.querySelectorAll('.oc-tfs-item') ?? [])];
  for (const item of items) {
    expect(item.querySelectorAll('.oc-tfs-label')).toHaveLength(1);
    expect(item.querySelectorAll('.oc-tfs-value')).toHaveLength(1);
  }
  expect(grown?.querySelectorAll('.oc-tfs-bar').length).toBe(1);
  expect(grown?.querySelectorAll('.oc-tfs-gauge .oc-gauge').length).toBe(2);
  expect(grown?.querySelector('[data-stat="model"] .oc-tfs-model')?.textContent).toBe('Opus 4');
  expect(grown?.querySelector('[data-stat="context"] .oc-tfs-label')?.textContent).toBe('context');
});

test('an unknown account leaves the grid, never "not available"', () => {
  const target = setup(usage({ account: null }), 390);
  toggle(target).click();
  flushSync();
  const grown = stats(target);
  expect(grown?.querySelector('[data-stat="account"]')).toBeNull();
  expect(grown?.textContent).not.toContain('not available');
  expect(grown?.querySelector('[data-stat="cost"]')).not.toBeNull();
});

test('a reset under a day out also says its clock time; a day or more out never does', () => {
  const soon = new Date(Date.now() + 2 * 3600 * 1000).toISOString();
  const payload = usage({ account: account({ windows: [
    { kind: 'five_hour', label: '5h', used_pct: 41, resets_at: soon },
    { kind: 'seven_day', label: '7d', used_pct: 12, resets_at: FAR_RESET },
  ] } as Partial<AccountUsage>) });
  const target = setup(payload, 390);
  toggle(target).click();
  flushSync();
  const grown = stats(target);
  expect(grown?.querySelector('[data-stat="window:five_hour"]')?.textContent).toMatch(/at \d{1,2}:\d{2} (am|pm)/);
  expect(grown?.querySelector('[data-stat="window:seven_day"]')?.textContent).not.toMatch(/ at /);
});

test('a login problem row reaches the grown bar too', () => {
  const payload = usage({ account: account({ credential_state: 'expired', windows: [] }) });
  const target = setup(payload);
  toggle(target).click();
  flushSync();
  expect(region(target)?.textContent).toContain('expired, log in again');
});

test('absent: the grown bar says nothing spent yet and draws no figures', () => {
  const target = setup({ state: 'absent' } as SessionTokenUsage);
  toggle(target).click();
  flushSync();
  const grown = region(target);
  expect(grown?.textContent).toContain('nothing spent yet');
  expect(grown?.querySelector('.oc-tfs-bar')).toBeNull();
});

test('NO REFIT: toggling never resizes the window and never swaps the in-flow bar out', () => {
  const target = setup(usage());
  const button = toggle(target);
  const resized = vi.fn();
  window.addEventListener('resize', resized);
  button.click();
  flushSync();
  button.click();
  flushSync();
  window.removeEventListener('resize', resized);
  expect(resized).not.toHaveBeenCalled();
  expect(toggle(target)).toBe(button);
  expect(region(target)).not.toBe(button);
  expect(button.contains(region(target))).toBe(false);
});

test('NO REFIT: the grown region is an absolutely positioned overlay anchored to the bottom', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const source = fs.readFileSync(path.resolve(import.meta.dirname, './TerminalFoot.svelte'), 'utf-8');
  const style = source.slice(source.indexOf('<style>'), source.indexOf('</style>'));
  const slot = style.slice(style.indexOf('.oc-tf-slot {'));
  expect(slot.slice(0, slot.indexOf('}'))).toMatch(/position:\s*relative/);
  const grownSource = fs.readFileSync(path.resolve(import.meta.dirname, './FootGrown.svelte'), 'utf-8');
  const grownStyle = grownSource.slice(grownSource.indexOf('<style>'), grownSource.indexOf('</style>'));
  const grown = grownStyle.slice(grownStyle.indexOf('.oc-tf-grown {'));
  const rule = grown.slice(0, grown.indexOf('}'));
  expect(rule).toMatch(/position:\s*absolute/);
  expect(rule).toMatch(/bottom:\s*0/);
  expect(rule).toMatch(/overflow:\s*hidden/);
});

function ownClasses(el: Element): string[] {
  return [...el.classList].filter((c) => !c.startsWith('svelte-'));
}

function statGroups(target: HTMLElement): string[][] {
  return [...(stats(target)?.querySelectorAll('.oc-tfs-group') ?? [])].map((group) =>
    [...group.querySelectorAll('.oc-tfs-item')].map((item) => item.getAttribute('data-stat') ?? ''));
}

test('EXPANDED: three groups in #422 order - context/model/tokens, then the two windows, then cost/account', () => {
  const target = setup(usage(), 390);
  toggle(target).click();
  flushSync();
  expect(statGroups(target)).toEqual([
    ['context', 'model', 'tokens'],
    ['window:five_hour', 'window:seven_day'],
    ['cost', 'account'],
  ]);
});

test('EXPANDED: an unhealthy login puts the login row beside cost and account, with no empty window group (#422)', () => {
  const payload = usage({ account: account({ credential_state: 'expired', windows: [] }) });
  const target = setup(payload, 390);
  toggle(target).click();
  flushSync();
  expect(statGroups(target)).toEqual([['context', 'model', 'tokens'], ['cost', 'account', 'login']]);
});

test('EXPANDED: a healthy login with no window data puts the limits row beside cost and account (#422)', () => {
  const payload = usage({ account: account({ credential_state: 'ok', windows: [] }) });
  const target = setup(payload, 390);
  toggle(target).click();
  flushSync();
  expect(statGroups(target)).toEqual([['context', 'model', 'tokens'], ['cost', 'account', 'limits']]);
});

test('COLLAPSED: the skinny bar draws the model then the meters group, no grid and no extra rows (#422)', () => {
  const target = setup(usage(), 390);
  const button = toggle(target);
  expect(button.querySelector('.oc-tfs')).toBeNull();
  expect(button.querySelector('[data-row]')).toBeNull();
  const direct = Array.from(button.children).map(ownClasses);
  expect(direct).toEqual([['oc-tf-model'], ['oc-tf-meters']]);
  expect(Array.from(button.querySelectorAll('.oc-tf-meters > .oc-tf-meter')).length).toBe(3);
});

test('EXPANDED, wide: the grown bar draws the band stats and the columns control center', () => {
  const target = setup(usage(), 1440);
  toggle(target).click();
  flushSync();
  const grown = region(target)!;
  expect(grown.querySelector('.oc-tfs')?.getAttribute('data-layout')).toBe('band');
  expect(grown.querySelector('.scc')?.getAttribute('data-layout')).toBe('columns');
});

test('EXPANDED, narrow: the grown bar draws tile stats and an accordion control center', () => {
  const target = setup(usage(), 390);
  toggle(target).click();
  flushSync();
  const grown = region(target)!;
  expect(grown.querySelector('.oc-tfs')?.getAttribute('data-layout')).toBe('tiles');
  expect(grown.querySelector('.scc')?.getAttribute('data-layout')).toBe('accordion');
});
