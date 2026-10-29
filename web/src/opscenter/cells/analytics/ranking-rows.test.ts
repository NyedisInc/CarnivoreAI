import { describe, expect, test } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

describe('ranking and cost list rows', () => {
  test('rows grow to share spare height but never shrink below their natural height (#1779)', () => {
    const src = readFileSync(join(process.cwd(), 'src/opscenter/cells/analytics/TimelineView.svelte'), 'utf8');
    const rule = src.match(/\.analytics-ranking-room > \.analytics-ranking:not\(\.analytics-ranking--bare\) li \{([^}]*)\}/);
    expect(rule).not.toBeNull();
    const flex = (rule?.[1]!.match(/flex:\s*(\d+)\s+(\d+)\s+([^;]+);/) ?? []).slice(1);
    expect(Number(flex[1])).toBe(0);
    const list = src.match(/\.analytics-ranking-room > \.analytics-ranking:not\(\.analytics-ranking--bare\) \{([^}]*)\}/);
    expect(list?.[1]).not.toMatch(/\bgap:/);
    expect(flex[2]!.trim()).toBe('auto');
  });
});
