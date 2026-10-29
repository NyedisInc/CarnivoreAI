import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

type Rule = { selector: string; specificity: number; order: number; minHeight: string };

export function minHeightRules(css: string, classes: string[]): Rule[] {
  const rules: Rule[] = [];
  let order = 0;
  for (const match of css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const decl = /(?:^|;)\s*min-height\s*:\s*([^;]+)/.exec(match[2]!);
    order += 1;
    if (!decl) continue;
    for (const selector of match[1]!.split(',').map((part) => part.trim())) {
      const parts = selector.split('.').slice(1);
      if (!selector.startsWith('.') || parts.length === 0 || parts.some((part) => !classes.includes(part))) continue;
      rules.push({ selector, specificity: parts.length, order, minHeight: decl[1]!.trim() });
    }
  }
  return rules;
}

export function winningMinHeight(css: string, classes: string[]): string | null {
  const [winner] = minHeightRules(css, classes).sort((a, b) => b.specificity - a.specificity || b.order - a.order);
  return winner?.minHeight ?? null;
}

const source = readFileSync(new URL('./TimelineView.svelte', import.meta.url), 'utf8');
const style = source.slice(source.indexOf('<style'));
const CLASSES = ['analytics-plot', 'analytics-plot--yield'];

describe('the tokens card plot yield rule', () => {
  test('the real stylesheet gives a yielding plot a zero min-height, not the 70px floor', () => {
    expect(winningMinHeight(style, ['analytics-plot'])).toBe('70px');
    expect(winningMinHeight(style, CLASSES)).toBe('0');
  });

  test('a dropped band collapses to nothing: zero height, no flex growth, no 70px floor', () => {
    expect(winningMinHeight(style, [...CLASSES.slice(0, 1), 'analytics-plot--dropped'])).toBe('0');
    expect(style).toMatch(/\.analytics-plot\.analytics-plot--dropped\s*\{[^}]*flex:\s*none;[^}]*height:\s*0;/);
  });

  test('the resolver can fail: a bare yield rule declared before the base rule loses', () => {
    const reversed = '.analytics-plot--yield { min-height: 0; }\n.analytics-plot { min-height: 70px; }';
    expect(winningMinHeight(reversed, CLASSES)).toBe('70px');
  });
});
