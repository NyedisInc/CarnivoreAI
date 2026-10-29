/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import TerminalFoot from './TerminalFoot.svelte';
import type { AccountUsage, SessionTokenUsage } from '../../api/types';

let currentPayload: SessionTokenUsage | null = null;
let currentRows: unknown[] = [];
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    sessions: { get data() { return currentRows; } },
    sessionUsage: vi.fn(() => ({ data: currentPayload, status: 'ok' })),
    releaseSessionUsage: vi.fn(),
  };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  currentPayload = null;
  currentRows = [];
  try { globalThis.localStorage?.clear(); } catch {  }
});

function baseUsage(overrides: Partial<SessionTokenUsage> = {}): SessionTokenUsage {
  return {
    state: 'ok',
    family: 'claude',
    model: 'claude-opus-4',
    model_display_name: 'Opus 4',
    model_cost_tier: 3,
    effort: null,
    input_tokens: 1000,
    output_tokens: 500,
    cache_read_input_tokens: null,
    cache_creation_input_tokens: null,
    total_tokens: 1500,
    cost_estimate_usd: 0.5,
    context_used_tokens: 1000,
    context_window_tokens: 200000,
    context_remaining_pct: 99.5,
    as_of: '2026-09-24T00:00:00Z',
    detail: null,
    account: null,
    ...overrides,
  };
}

function baseAccount(overrides: Partial<AccountUsage> = {}): AccountUsage {
  return {
    id: 'acct-1',
    name: 'Claude Code - Acme',
    short_name: null,
    provider: 'claude',
    plan: null,
    identity: null,
    credential_state: 'ok',
    fetched_at: null,
    next_poll_at: null,
    error: null,
    windows: [],
    color: null,
    managed: false,
    ...overrides,
  };
}

function setup(payload: SessionTokenUsage | null, width = 600): HTMLElement {
  currentPayload = payload;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(TerminalFoot, { target, props: { sessionId: 'ses_1', width } }));
  flushSync();
  return target;
}

test('a model with no effort renders the model name and no "not available" effort span', () => {
  const target = setup(baseUsage({ effort: null }));
  expect(target.querySelector('.oc-tf-model-name')?.textContent).toBe('Opus 4');
  expect(target.querySelector('.oc-tf-effort')).toBeNull();
  expect(target.querySelector('.oc-tf-model')?.textContent).not.toContain('not available');
});

test('a model with a measured effort renders it beside the model name', () => {
  const target = setup(baseUsage({ effort: 'high' }));
  expect(target.querySelector('.oc-tf-model-name')?.textContent).toBe('Opus 4');
  expect(target.querySelector('.oc-tf-effort')?.textContent).toBe('high');
});

test('each recorded effort level paints its own class on the effort text', () => {
  for (const level of ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode']) {
    const target = setup(baseUsage({ effort: level }));
    const span = target.querySelector('.oc-tf-effort');
    expect(span?.textContent).toBe(level);
    expect(span?.classList.contains('effort-level')).toBe(true);
    expect(span?.classList.contains(`effort--${level}`)).toBe(true);
    expect(span?.hasAttribute('title')).toBe(false);
  }
});

test('an effort the mapping does not know keeps the plain dim text', () => {
  const target = setup(baseUsage({ effort: 'auto' }));
  const span = target.querySelector('.oc-tf-effort');
  expect(span?.textContent).toBe('auto');
  expect(span?.classList.contains('effort-level')).toBe(false);
});

test('an effort that is only whitespace is treated the same as absent', () => {
  const target = setup(baseUsage({ effort: '   ' }));
  expect(target.querySelector('.oc-tf-effort')).toBeNull();
});

test('the effort is never hidden: a narrow cell still shows it beside the model name (Alex, 2026-09-29)', () => {
  const target = setup(baseUsage({ effort: 'high' }), 200);
  expect(target.querySelector('.oc-tf-effort')?.textContent).toBe('high');
});

test('a wide cell renders every collapsed field: context percent and fraction, both resets, no tokens', () => {
  const target = setup(baseUsage({
    context_used_tokens: 447000,
    context_window_tokens: 1000000,
    context_remaining_pct: 55,
    account: baseAccount({
      windows: [
        { kind: 'five_hour', label: '5h', used_pct: 26, resets_at: '2026-09-27T12:00:00Z' } as never,
        { kind: 'seven_day', label: '7d', used_pct: 29, resets_at: '2026-10-01T00:00:00Z' } as never,
      ],
    }),
  }), 1400);
  const button = target.querySelector('button.oc-tf');
  const text = button?.textContent ?? '';
  expect(text).toContain('447k/1M');
  expect(target.querySelector('.oc-tf-meter .oc-tf-num')?.textContent).toMatch(/^\d+%$/);
  expect(target.querySelectorAll('.oc-tf-reset').length).toBe(2);
  expect(button?.querySelector('[data-row="tokens"]')).toBeNull();
  expect(text).not.toMatch(/1k.*500|500.*1k/);
});

test('the fold ladder: the resets drop as the cell narrows, and tokens never appear', () => {
  const usage = baseUsage({
    account: baseAccount({
      windows: [
        { kind: 'five_hour', label: '5h', used_pct: 26, resets_at: '2026-09-27T12:00:00Z' } as never,
      ],
    }),
  });

  const wide = setup(usage, 1400);
  expect(wide.querySelector('.oc-tf-reset')).not.toBeNull();
  expect(wide.querySelector('button.oc-tf [data-row="tokens"]')).toBeNull();

  const noReset = setup(usage, 1200);
  expect(noReset.querySelector('.oc-tf-reset')).toBeNull();
  expect(noReset.querySelector('.oc-tf-model-name')).not.toBeNull();
});

test('the collapsed bar never shows account or cost at the widest width; the expanded view still shows both', () => {
  const usage = baseUsage({
    cost_estimate_usd: 0.5,
    account: baseAccount({ name: 'Claude Code - Acme' }),
  });
  const target = setup(usage, 2560);

  const collapsedButton = target.querySelector('button.oc-tf');
  expect(collapsedButton?.querySelector('[data-row="cost"]')).toBeNull();
  expect(collapsedButton?.querySelector('[data-row="account"]')).toBeNull();
  expect(collapsedButton?.textContent ?? '').not.toContain('Acme');
  expect(collapsedButton?.textContent ?? '').not.toContain('$0.50');

  (collapsedButton as HTMLButtonElement)?.click();
  flushSync();
  const expandedRegion = target.querySelector('.oc-tfs');
  expect(expandedRegion?.querySelector('[data-stat="cost"]')).not.toBeNull();
  expect(expandedRegion?.querySelector('[data-stat="account"]')).not.toBeNull();
  expect(expandedRegion?.textContent ?? '').toContain('Acme');
  expect(expandedRegion?.textContent ?? '').toContain('$0.50');
});

test('the context meter prints the compact "447k/1M" form, never the full sentence', () => {
  const target = setup(baseUsage({
    context_used_tokens: 447000,
    context_window_tokens: 1000000,
  }), 600);
  const text = target.textContent ?? '';
  expect(text).toContain('447k/1M');
  expect(text).not.toContain('447,000');
});

test('the percentages outlive the bars: the context percent survives with no bar at the narrowest width', () => {
  const usage = baseUsage({
    context_used_tokens: 447000,
    context_window_tokens: 1000000,
    account: { name: 'work', credential_state: 'ok', windows: [] } as never,
  });

  const core = setup(usage, 300);
  expect(core.querySelector('.oc-tf-num')).not.toBeNull();
  expect(core.querySelector('.oc-tf-bar')).toBeNull();

  const bars = setup(usage, 470);
  expect(bars.querySelector('.oc-tf-bar')).not.toBeNull();
  const barsNums = Array.from(bars.querySelectorAll('.oc-tf-num')).map((n) => n.textContent);
  expect(barsNums).toContain('447k/1M');

  const wide = setup(usage, 900);
  expect(wide.querySelector('.oc-tf-bar')).not.toBeNull();
  expect(wide.querySelector('.oc-tf-num')).not.toBeNull();
  expect(wide.querySelector('[data-row="account"]')).toBeNull();
});

test('the narrowest width still shows the effort and all three percentages, no bars', () => {
  const target = setup(baseUsage({
    effort: 'medium',
    context_used_tokens: 293000,
    context_window_tokens: 1000000,
    account: baseAccount({ windows: [
      { kind: 'five_hour', label: '5h', used_pct: 23, window_seconds: 18000, resets_at: null },
      { kind: 'seven_day', label: '7d', used_pct: 81, window_seconds: 604800, resets_at: null },
    ] }),
  }), 300);
  expect(target.querySelector('.oc-tf-effort')?.textContent).toBe('medium');
  const pcts = Array.from(target.querySelectorAll('.oc-tf-pct')).map((n) => n.textContent?.trim());
  expect(pcts).toHaveLength(3);
  expect(pcts.every((p) => /^\d+%$/.test(p ?? ''))).toBe(true);
  expect(target.querySelector('.oc-tf-bar')).toBeNull();
});

test('the model and meter groups never declare min-width: 0, the line the overlap bug lived on', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const source = fs.readFileSync(path.resolve(import.meta.dirname, './TerminalFoot.svelte'), 'utf-8');
  const style = source.slice(source.indexOf('<style>'), source.indexOf('</style>'));
  const modelRule = style.slice(style.indexOf('.oc-tf-model {'), style.indexOf('.oc-tf-model-name {'));
  const meterRule = style.slice(style.indexOf('.oc-tf-meter {'), style.indexOf('.oc-tf-label {'));
  expect(modelRule).not.toMatch(/min-width:\s*0/);
  expect(meterRule).not.toMatch(/min-width:\s*0/);
});

// there is nothing

test('one layout at every viewport: the model leads, the three meters follow as one group', async () => {
  const { viewport } = await import('../../engine/viewport.svelte');
  const usage = baseUsage({
    account: baseAccount({
      windows: [
        { kind: 'five_hour', label: '5h', used_pct: 26, resets_at: '2026-09-27T12:00:00Z' } as never,
        { kind: 'seven_day', label: '7d', used_pct: 29, resets_at: '2026-10-01T00:00:00Z' } as never,
      ],
    }),
  });
  for (const wide of [true, false]) {
    viewport.wide = wide;
    viewport.phone = !wide;
    try {
      const target = setup(usage, 1400);
      const button = target.querySelector('button.oc-tf');
      const direct = Array.from(button?.children ?? []).map((el) => el.className.split(' ').filter((c) => !c.startsWith('svelte-')));
      expect(direct).toEqual([['oc-tf-model'], ['oc-tf-meters']]);
      const labels = Array.from(button?.querySelectorAll('.oc-tf-meters > .oc-tf-meter > .oc-tf-label') ?? []).map((el) => el.textContent);
      expect(labels).toEqual(['ctx', '5h', '7d']);
    } finally {
      viewport.wide = false;
      viewport.phone = true;
    }
  }
});

test('one rate-limit window: the meters group holds exactly two meters', () => {
  const target = setup(baseUsage({
    account: baseAccount({
      windows: [{ kind: 'five_hour', label: '5h', used_pct: 26, resets_at: '2026-09-27T12:00:00Z' } as never],
    }),
  }), 1400);
  expect(target.querySelectorAll('button.oc-tf > .oc-tf-meters > .oc-tf-meter').length).toBe(2);
});

test('the grown overlay never renders the collapsed meters group, even on desktop', async () => {
  const { viewport } = await import('../../engine/viewport.svelte');
  viewport.wide = true;
  viewport.phone = false;
  try {
    const target = setup(baseUsage({
      account: baseAccount({
        windows: [{ kind: 'five_hour', label: '5h', used_pct: 26, resets_at: '2026-09-27T12:00:00Z' } as never],
      }),
    }), 1400);
    (target.querySelector('button.oc-tf') as HTMLButtonElement)?.click();
    flushSync();
    const expandedRegion = target.querySelector('.oc-tf-grown');
    expect(expandedRegion?.querySelector('.oc-tf-meters')).toBeNull();
    expect(expandedRegion?.querySelectorAll('.oc-tfs-bar').length).toBeGreaterThan(0);
  } finally {
    viewport.wide = false;
    viewport.phone = true;
  }
});

test('the meters group is centered and every bar is one fixed, equal width', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const source = fs.readFileSync(path.resolve(import.meta.dirname, './FootMeters.svelte'), 'utf-8');
  const style = source.slice(source.indexOf('<style>'), source.indexOf('</style>'));
  const group = style.slice(style.indexOf('.oc-tf-meters {'), style.indexOf('}', style.indexOf('.oc-tf-meters {')));
  expect(group).toMatch(/margin-inline:\s*auto/);
  expect(group).toMatch(/justify-content:\s*center/);
  const bar = style.slice(style.indexOf('.oc-tf-meters .oc-tf-bar {'), style.indexOf('}', style.indexOf('.oc-tf-meters .oc-tf-bar {')));
  const widths = [...bar.matchAll(/(?:flex:\s*0 0|min-width:|max-width:)\s*(\d+)px/g)].map((m) => m[1]);
  expect(widths).toEqual(['112', '112', '112']);
});

test('the model name wears the provider mark: anthropic for claude, openai for codex, none for another family', () => {
  const markFor = (family: string | null): string | null => {
    currentRows = [{ session: { id: 'ses_1' }, agent_family: family, tmux_session: 'cloude_x' }];
    const target = setup(baseUsage());
    const mark = target.querySelector('.oc-tf-model [data-fw="model-mark"]');
    const svg = mark?.querySelector('svg') ?? null;
    expect(mark === null || svg !== null).toBe(true);
    return mark?.getAttribute('data-mark') ?? null;
  };
  expect(markFor('claude')).toBe('anthropic');
  expect(markFor('codex')).toBe('openai');
  expect(markFor(null)).toBeNull();
  expect(document.querySelectorAll('.oc-tf-model-name').length).toBe(3);
});
