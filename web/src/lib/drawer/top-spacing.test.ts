import fs from 'node:fs';
import path from 'node:path';
import { expect, test } from 'vitest';

const LIB = path.resolve(__dirname, '..');
const read = (rel: string): string => fs.readFileSync(path.join(LIB, rel), 'utf8');

function rule(css: string, selector: string): string {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const m = new RegExp(`(?:^|\\n)\\s*${esc}\\s*\\{([^}]*)\\}`).exec(css);
  if (!m) throw new Error(`no rule for ${selector}`);
  return m[1]!;
}
const decl = (body: string, prop: string): string => new RegExp(`(?:^|[;\\s])${prop}\\s*:\\s*([^;]+);`).exec(body)?.[1]?.trim() ?? '';

const rail = read('sidebar-widgets/sidebar-rail.css');
const header = read('drawer/DrawerHeader.svelte');
const stats = read('drawer-tabs/DrawerStats.svelte');

test('row 1: the title bar spaces its clusters with tokens', () => {
  expect(decl(rule(header, '.session-sidebar-heading'), 'gap')).toBe('var(--oc-space-3)');
  expect(decl(rule(rail, '.sbr-controls-slot'), 'gap')).toBe('var(--oc-space-1)');
  expect(decl(rule(rail, 'body.sidebar-layout-rail .session-sidebar-header'), 'padding')).toBe('0 var(--oc-space-3)');
});

test('row 2: the counts strip has room at its edges and between its items', () => {
  expect(decl(rule(stats, '.dst-row'), 'padding')).toBe('var(--oc-space-2) var(--oc-space-3)');
  expect(decl(rule(stats, '.dst-row'), 'gap')).toBe('var(--oc-space-2)');
  expect(decl(rule(stats, '.dst-counts'), 'gap')).toBe('var(--oc-space-2)');
  expect(decl(rule(stats, '.dst-act'), 'padding')).toBe('0 var(--oc-space-2)');
});
