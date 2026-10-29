import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

const row = readFileSync('src/cplugs/huddle/TaskManagerRow.svelte', 'utf8');
const rule = (selector: string): string => new RegExp(`\\n    ${selector.replace('.', '\\.')} \\{([^}]*)\\}`).exec(row)?.[1] ?? '';

describe('the row title keeps a readable minimum at any width', () => {
  test('the head line wraps at every width, not only inside a narrow container query', () => {
    expect(rule('.hdr-line')).toMatch(/flex-wrap:\s*wrap/);
  });

  test('the title basis is the minimum token, so what does not fit beside it wraps instead of shrinking it', () => {
    expect(rule('.tkm-text')).toMatch(/flex:\s*1 1 var\(--tkm-title-min\)/);
    expect(rule('.hdr-line')).toMatch(/--tkm-title-min:\s*\d+(\.\d+)?em/);
  });

  test('the time and edit key stay one unflexing unit', () => {
    expect(rule('.tkm-when')).toMatch(/flex:\s*none/);
  });
});
