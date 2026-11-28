/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TabStrip from '../../opscenter/shell/TabStrip.svelte';
import { NOT_MEASURED, type AgentMarkFacts } from '../sessions/agent-marks';
import { applyComet, cometKind } from './comet';
import { comet, refreshComet } from './comet-pref.svelte';

const facts = (over: Partial<AgentMarkFacts>): AgentMarkFacts => ({ ...NOT_MEASURED, family: 'claude', ...over });
const UNREAD = facts({ status: 'finished_unread', unread: true });
const QUESTION = facts({ status: 'question' });
const NOTICE = facts({ status: 'notice' });
const WORKING = facts({ status: 'working' });

let stored: Record<string, unknown> = {};
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  stored = {};
  (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge = { read: (field: string, fallback: () => unknown) => (field in stored ? stored[field] : fallback()) };
  refreshComet();
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  delete (globalThis as { PreferenceBridge?: unknown }).PreferenceBridge;
  document.body.replaceChildren();
  document.documentElement.removeAttribute('data-comet-color');
  document.documentElement.style.removeProperty('--oc-comet-lap');
});

function strip(items: { id: string; face: AgentMarkFacts }[], active: string): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const rows = items.map((i) => ({ id: i.id, name: i.id, family: 'claude', face: i.face }));
  app = mount(TabStrip, { target, props: { items: rows, active, onSelect: () => {} } });
  flushSync();
  return target;
}
const wrap = (root: HTMLElement, id: string): HTMLElement => root.querySelector(`[data-tab="${id}"]`)!.closest('.oc-tabwrap') as HTMLElement;

test('unread, question and notice earn a comet; working and idle do not', () => {
  expect(cometKind(UNREAD)).toBe('unread');
  expect(cometKind(QUESTION)).toBe('question');
  expect(cometKind(facts({ status: 'idle', startupGate: 'awaiting_startup_prompt' }))).toBe('question');
  expect(cometKind(NOTICE)).toBe('notice');
  expect(cometKind(WORKING)).toBeNull();
  expect(cometKind(facts({ status: 'idle' }))).toBeNull();
  expect(cometKind(null)).toBeNull();
  expect(cometKind(facts({ status: 'asleep', unread: true }))).toBe('unread');
  expect(cometKind(facts({ status: 'asleep', unread: false }))).toBeNull();
});

test('a window wears it, clears with the state and the switch off removes it; the lap follows the setting', () => {
  const frame = document.createElement('div');
  applyComet(frame, cometKind(UNREAD), comet.lap);
  expect(frame.getAttribute('data-comet')).toBe('unread');
  expect(frame.style.getPropertyValue('--oc-comet-delay')).toMatch(/^-?[\d.]+s$/);
  applyComet(frame, cometKind(QUESTION), comet.lap);
  expect(frame.getAttribute('data-comet')).toBe('question');
  applyComet(frame, cometKind(WORKING), comet.lap);
  expect(frame.hasAttribute('data-comet')).toBe(false);

  stored = { comet_lap_seconds: 7.5, comet_unread_color: 'green' };
  refreshComet();
  expect(document.documentElement.style.getPropertyValue('--oc-comet-lap')).toBe('7.5s');
  expect(document.documentElement.getAttribute('data-comet-color')).toBe('green');
  stored = { comet_lap_seconds: 99 };
  refreshComet();
  expect(comet.lap).toBe(3);
  stored = { comet_on: false };
  refreshComet();
  expect(comet.on).toBe(false);
});

test('a background tab wears it on the tab, the showing tab does not, and the switch off removes it', () => {
  const root = strip([{ id: 'terminal:a', face: UNREAD }, { id: 'terminal:b', face: UNREAD }, { id: 'terminal:c', face: WORKING }], 'terminal:a');
  expect(wrap(root, 'terminal:a').hasAttribute('data-comet')).toBe(false);
  expect(wrap(root, 'terminal:b').getAttribute('data-comet')).toBe('unread');
  expect(wrap(root, 'terminal:c').hasAttribute('data-comet')).toBe(false);

  stored = { comet_on: false };
  refreshComet();
  flushSync();
  expect(wrap(root, 'terminal:b').hasAttribute('data-comet')).toBe(false);
});

function head(t: number, A: number): { x: number; y: number } {
  const a = A / (A + 1);
  const b = 1 - a;
  const u = (((t % 1) + 1) % 1) * 4;
  const clamp = (lo: number, v: number, hi: number): number => Math.min(hi, Math.max(lo, v));
  return { x: clamp(-a, Math.max(Math.min(u, 2 - u), u - 4), a), y: clamp(-b, Math.max(1 - u, u - 3), b) };
}

function angle(t: number, A: number): number {
  const p = head(t, A);
  return (((Math.atan2(p.x, p.y) * 180) / Math.PI) % 360 + 360) % 360;
}

const along = (from: number, to: number): number => ((((to - from) % 1) + 1) % 1) * 4;

const BEHIND = [150, 115, 80, 46, 12, 6, 0];

test('the head moves at an even speed on every edge', () => {
  const steps = 20;
  for (let i = 0; i < steps; i++) {
    const p = head(i / steps, 4);
    const q = head((i + 1) / steps, 4);
    expect(Math.hypot(q.x - p.x, q.y - p.y)).toBeCloseTo(4 / steps, 9);
  }
  const q = head(0.25, 1);
  expect(q.x).toBeCloseTo(0.5, 9);
  expect(q.y).toBeCloseTo(0, 9);
  expect(angle(0.25, 1)).toBeCloseTo(90, 9);
});

test('the tail is the same share of the border wherever the head is, and the stops rise from tail to head', () => {
  for (const t of [0, 0.25, 0.21]) {
    const tailEnd = (t - 150 / 360 + 1) % 1;
    expect(along(tailEnd, t)).toBeCloseTo((150 / 360) * 4, 9);
  }
  for (const t of [0, 0.03, 0.2, 0.21, 0.25, 0.4, 0.5, 0.75, 0.9, 0.99]) {
    const g0 = angle(t - 150 / 360, 4);
    const rel = BEHIND.map((d) => (((angle(t - d / 360, 4) - g0) % 360) + 360) % 360);
    for (let k = 1; k < rel.length; k++) expect(rel[k]).toBeGreaterThan(rel[k - 1]);
  }
});

test('the CSS uses 4 mitered GPU linear-gradient ribbon strips with zero @property/conic-gradient; applyComet mounts, sizes and clears the ribbon', () => {
  const css = readFileSync('src/lib/comet/comet.css', 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  expect(css).not.toContain('@property');
  expect(css).not.toContain('conic-gradient');
  expect(css).not.toContain('atan2(');
  expect(css).toContain('.comet-ribbon-ring');
  expect(css).toContain('linear-gradient(to right,');
  expect(css).toContain('linear-gradient(to bottom,');
  expect(css).toContain('linear-gradient(to left,');
  expect(css).toContain('linear-gradient(to top,');

  const frame = document.createElement('div');
  frame.getBoundingClientRect = () => ({ width: 400, height: 100 }) as DOMRect;
  applyComet(frame, 'unread', 3);
  expect(frame.style.getPropertyValue('--oc-comet-aspect')).toBe('4.0000');
  const ring = frame.querySelector(':scope > .comet-ribbon-ring') as HTMLElement | null;
  expect(ring).not.toBeNull();
  expect(ring!.querySelectorAll('.comet-edge > .comet-bar')).toHaveLength(4);
  expect(ring!.style.getPropertyValue('--cm-p')).toBe('1000.00px');
  applyComet(frame, null, 3);
  expect(frame.style.getPropertyValue('--oc-comet-aspect')).toBe('');
  expect(frame.querySelector(':scope > .comet-ribbon-ring')).toBeNull();
});
