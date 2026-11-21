import { readFileSync } from 'node:fs';
import { expect, test } from 'vitest';
import { edgeFade } from './strip-edge-fade';

const css = (): string => readFileSync(new URL('./ZoneKeys.svelte', import.meta.url), 'utf8');
const rule = (selector: string): string => {
  const at = css().indexOf(`${selector} {`);
  expect(at, `rule ${selector} exists`).toBeGreaterThan(-1);
  return css().slice(at, css().indexOf('}', at));
};

test('the fade names only the edge that hides keys', () => {
  expect(edgeFade(0, 1085, 1104)).toBe('end');
  expect(edgeFade(19, 1085, 1104)).toBe('start');
  expect(edgeFade(10, 1085, 1104)).toBe('both');
  expect(edgeFade(0, 1085, 1085)).toBeNull();
  expect(edgeFade(0.4, 1085, 1085.6)).toBeNull();
});

test('the side strip scrolls only up and down, with no scroll bar, so keys keep their full width', () => {
  const side = rule(".rail__sections[data-motion]");
  expect(side).toContain('overflow-x: hidden');
  expect(side).toContain('overflow-y: auto');
  expect(side).toContain('scrollbar-width: none');
  expect(rule(".rail__sections[data-motion]::-webkit-scrollbar")).toContain('display: none');
});

test('the bottom strip scrolls only sideways, with no scroll bar', () => {
  const bottom = rule(".rail__sections[data-motion][data-axis='x']");
  expect(bottom).toContain('overflow-x: auto');
  expect(bottom).toContain('overflow-y: hidden');
});
