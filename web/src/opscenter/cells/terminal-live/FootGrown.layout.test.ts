/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { mount, unmount, flushSync } from 'svelte';
import FootStats from './FootStats.svelte';
import { sessionUsageLabels } from '../../api';
import type { SessionTokenUsage } from '../../api';
import { setLocale } from '../../../lib/i18n/index.svelte';
import ControlCenter from '../../../lib/session-control/ControlCenter.svelte';

setLocale('en');
const read = (path: string): string => readFileSync(new URL(path, import.meta.url), 'utf8');
const stats = read('./FootStats.svelte');
const rule = (css: string, selector: string): string => css.slice(css.indexOf(selector), css.indexOf('}', css.indexOf(selector)));

test('band: equal columns, label/value grid with a column gap', () => {
  const band = rule(stats, ".oc-tfs[data-layout='band'] {");
  expect(band).toContain('grid-template-columns: repeat(4, minmax(0, 1fr))');
  const group = rule(stats, ".oc-tfs[data-layout='band'] .oc-tfs-group {");
  expect(group).toContain('grid-template-columns: 17ch minmax(0, 1fr)');
  expect(group).toMatch(/column-gap: var\(--oc-space-\d\)/);
  expect(group).toContain('align-content: start');
});

test('control center: stops are base danger sm buttons aligned right', () => {
  const css = read('../../../lib/session-control/control-center.css');
  expect(rule(css, '.scc .scc-row > [data-scc-stop]')).toContain('justify-self: end');
  const target = document.createElement('div');
  document.body.append(target);
  const c = mount(ControlCenter, { target, props: { sessionId: 's', focus: null, layout: 'columns' } });
  flushSync();
  for (const b of target.querySelectorAll('[data-scc-act],[data-scc-stop]')) {
    expect(b.getAttribute('data-btn')).toBe('danger');
    expect(b.getAttribute('data-size')).toBe('sm');
  }
  void unmount(c);
});

test('limits block: same label/value grid as context and model, top aligned, on the control center columns', () => {
  const usage = {
    state: 'ok', model: 'claude-opus-5', input_tokens: 1, output_tokens: 1, cost_estimate_usd: 1,
    context_remaining_pct: 50, context_used_tokens: 1, context_window_tokens: 2,
    account: { id: 'a', name: 'work', credential_state: 'ok', windows: [
      { kind: 'five_hour', label: '5h', used_pct: 12, resets_at: null },
      { kind: 'seven_day', label: '7d', used_pct: 40, resets_at: '2099-01-01T00:00:00Z' },
    ] },
  } as unknown as SessionTokenUsage;
  const target = document.createElement('div');
  document.body.append(target);
  const c = mount(FootStats, { target, props: { model: sessionUsageLabels(usage, null), payload: usage, layout: 'band' } });
  flushSync();
  const groups = [...target.querySelectorAll('.oc-tfs-group')];
  expect(groups.length).toBe(4);
  const limits = groups[1];
  expect(limits.querySelectorAll('[data-stat^="window:"]').length).toBe(2);
  expect(groups[0].querySelector('[data-stat="context"]')).not.toBeNull();
  for (const g of groups) {
    const items = g.querySelectorAll(':scope > .oc-tfs-item');
    expect(items.length).toBeGreaterThan(0);
    for (const i of items) expect([...i.children].map((e) => e.tagName)).toEqual(['DT', 'DD']);
  }
  const band = rule(stats, ".oc-tfs[data-layout='band'] {");
  expect(band).toContain('repeat(4, minmax(0, 1fr))');
  expect(band).toContain('column-gap: 0');
  void unmount(c);
});

test('top and bottom rows share the same four column lines, and every stop is one size', () => {
  const css = read('../../../lib/session-control/control-center.css');
  const cols = rule(css, ".scc[data-layout='columns'] {");
  const columns = (r: string) => /grid-template-columns: ([^;]+);/.exec(r)?.[1];
  expect(columns(rule(stats, ".oc-tfs[data-layout='band'] {"))).toBe(columns(cols));
  expect(stats).not.toMatch(/grid-column: span/);
  const stop = rule(css, '.scc [data-scc-act],\n  .scc [data-scc-stop] {');
  expect(stop).toContain('min-width: 9ch');
  expect(stop).not.toMatch(/padding|background|height/);
});

test('a row with no meta line reserves no second grid row', () => {
  const css = read('../../../lib/session-control/control-center.css');
  const row = rule(css, '.scc .scc-row {');
  expect(row).toMatch(/grid-template-areas: 'type text num act';/);
  expect(css).not.toMatch(/grid-template-areas:[^;]*meta/);
  expect(rule(css, '.scc .scc-meta {')).toContain('grid-column: 2 / -1');
  expect(rule(css, '.scc .scc-row .scc-meta {')).toContain('grid-column: 1 / -1');
});
