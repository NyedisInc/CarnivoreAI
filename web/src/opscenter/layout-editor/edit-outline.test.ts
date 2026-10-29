import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

const read = (path: string): string => readFileSync(new URL(path, import.meta.url), 'utf8');
const overlay = read('./EditOverlay.svelte');
const zone = read('../../lib/drawer-zone/DrawerZone.svelte');
const glanceArea = read('../../lib/drawer-zone/GlanceArea.svelte');
const frame = read('../shell/CellFrame.svelte');
const corner = read('../shell/CornerMenu.svelte');

function ruleFor(source: string, selector: string): string {
  const at = source.indexOf(selector);
  expect(at, `${selector} has a rule`).toBeGreaterThan(-1);
  const open = source.indexOf('{', at);
  return source.slice(open + 1, source.indexOf('}', open));
}

const inFront = (token: string): RegExp[] => [
  new RegExp(`border:\\s*var\\(--oc-border\\)\\s+dashed\\s+var\\(--${token}\\)`),
  /position:\s*absolute/,
  /inset:\s*0/,
  /z-index:\s*60/,
  /pointer-events:\s*none/,
];

function highestFrameLayer(): number {
  return Math.max(...[...frame.matchAll(/z-index:\s*(\d+)/g)].map((m) => Number(m[1])));
}

describe('the edit outline', () => {
  test('uses the token the edit gear wears', () => {
    expect(ruleFor(corner, '.oc-frame-corner--edit,')).toMatch(/color:\s*var\(--oc-cyan\)/);
  });

  test.each([
    ['the home grid', "[data-layout-editing='home'] #launchpad-screen .oc-surface)::after"],
    ['the terminal grid', "[data-layout-editing='terminal'] #terminal-grid .oc-surface)::after"],
  ])('outlines %s in front of its widgets while it is being edited', (_name, selector) => {
    for (const re of inFront('oc-cyan')) expect(ruleFor(overlay, selector)).toMatch(re);
  });

  test('each widget\'s dashes are cyan and painted in front of every layer a frame draws (Joe, 2026-10-03)', () => {
    for (const selector of ["#terminal-grid .oc-cellslot[data-slot])::after", "#launchpad-screen .oc-cellslot[data-slot])::after"]) {
      const rule = ruleFor(overlay, selector);
      expect(rule).toMatch(/border:\s*1px dashed var\(--oc-cyan\);/);
      const z = Number(/z-index:\s*(\d+)/.exec(rule)?.[1]);
      expect(z).toBeGreaterThan(highestFrameLayer());
      expect(rule).toMatch(/pointer-events:\s*none/);
    }
  });

  test('outlines the sidebar widget area\'s widgets while editing, in front, drawn inside their edge', () => {
    expect(zone).toContain('class:dz-widgets--editing={editing}');
    expect(ruleFor(zone, '.dz-widgets--editing {')).toMatch(/position:\s*relative/);
    for (const re of inFront('oc-cyan')) expect(ruleFor(zone, '.dz-widgets--editing::after {')).toMatch(re);
  });

  test('the glance area wears yellow dashes in front on all four sides (Joe, 2026-10-03; placement: DrawerZone.test.ts)', () => {
    for (const re of inFront('oc-yellow')) expect(ruleFor(glanceArea, '.dz-garea::after {')).toMatch(re);
  });

  test('the widget area draws no sizer under its widgets (Joe, 2026-10-03)', () => {
    expect(zone).not.toMatch(/dz-grip|data-zone-grip|item-resize|role="separator"/);
  });

  test('no literal colour sneaks into any rule', () => {
    for (const rule of [ruleFor(zone, '.dz-widgets--editing::after {'), ruleFor(glanceArea, '.dz-garea::after {'), ruleFor(overlay, "#launchpad-screen .oc-surface)::after")]) {
      expect(rule).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(|hsl\(/i);
    }
  });
});
