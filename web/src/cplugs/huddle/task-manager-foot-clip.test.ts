import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync(new URL('./HuddleBody.svelte', import.meta.url), 'utf8').split('<style>')[1] ?? '';

function rule(selector: string): string {
  const found = [...css.matchAll(/(^|\n)\s*([^{}\n]+)\{([^}]*)\}/g)].filter((m) => (m[2] as string).trim() === selector);
  return (found[found.length - 1]?.[3] as string | undefined) ?? '';
}

describe('the control row at a narrow pop-out', () => {
  it('keeps the right group (hide completed, tell claude) at its whole width', () => {
    expect(rule('.hd-foot-right')).toMatch(/flex:\s*none/);
  });

  it('wraps rather than pushing the right group past the edge', () => {
    expect(rule('.hd-foot')).toMatch(/flex-wrap:\s*wrap/);
  });
});
