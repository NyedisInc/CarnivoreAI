import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

const read = (rel: string): string => readFileSync(new URL(rel, import.meta.url), 'utf8');
const TOKENS = read('../../../opscenter/tokens.css');
const BAR = read('./Mk2Bar.svelte');

function px(name: string): number {
  const value = new RegExp(`${name}:\\s*([^;]+);`).exec(TOKENS)?.[1]?.trim() ?? '';
  const alias = /^var\((--[\w-]+)\)$/.exec(value);
  return alias ? px(alias[1] as string) : Number.parseFloat(value);
}

function barTopPx(): number {
  const rule = /\.mk2-bar \{[^}]*?padding:\s*([^;]+);/.exec(BAR)?.[1] ?? '';
  const first = /var\((--[\w-]+)\)/.exec(rule)?.[1] ?? '';
  return px(first);
}

describe('TM Mark II search row spacing', () => {
  test('the space above the search row is the 12px step, not the old 8px', () => {
    expect(px('--oc-space-3')).toBe(12);
    expect(barTopPx()).toBe(px('--oc-space-3'));
  });

  test('the search row and chips start on the left edge of the title strip: the side padding is the 12px widget inset, not 8px', () => {
    const rule = /\.mk2-bar \{[^}]*?padding:\s*([^;]+);/.exec(BAR)?.[1] ?? '';
    const sides = [...rule.matchAll(/var\((--[\w-]+)\)/g)].map((m) => m[1] as string)[1] ?? '';
    expect(sides).toBe('--oc-widget-inset');
    expect(px(sides)).toBe(px('--oc-widget-inset'));
    expect(px('--oc-widget-inset')).toBe(12);
  });
});
