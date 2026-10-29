import { describe, expect, test } from 'vitest';
import { BUILTIN_CPLUGS, buildShipList, ORDER_HINT } from './builtin';
import type { CplugWeb } from './sdk';

const fake = (id: string) => ({ id }) as unknown as CplugWeb;

describe('web ship list discovery', () => {
  test('the real list is every shipped plugin, in the hinted order', () => {
    const ids = BUILTIN_CPLUGS.map((c) => c.id);
    expect(ids).toEqual(ORDER_HINT.filter((id) => ids.includes(id)).concat(ids.filter((id) => !ORDER_HINT.includes(id)).sort()));
    expect(ids).toContain('huddle');
  });

  test('a deleted plugin folder is simply absent', () => {
    const all = { './flow/index.ts': { flowCplug: fake('flow') }, './mcphealth/index.ts': { mcphealthCplug: fake('mcphealth') } };
    expect(buildShipList(all).map((c) => c.id)).toEqual(['flow', 'mcphealth']);
    expect(buildShipList({ './flow/index.ts': all['./flow/index.ts'] }).map((c) => c.id)).toEqual(['flow']);
  });

  test('the platform folder sdk is not a plugin; unhinted plugins follow by id', () => {
    const entries = { './sdk/index.ts': { x: 1 }, './zeta/index.ts': { zetaCplug: fake('zeta') }, './alpha/index.ts': { alphaCplug: fake('alpha') }, './flow/index.ts': { flowCplug: fake('flow') } };
    const ids = buildShipList(entries).map((c) => c.id);
    expect(ids).toEqual(['flow', 'alpha', 'zeta']);
  });

  test('a present plugin folder whose entry is broken fails, never silently drops', () => {
    expect(() => buildShipList({ './flow/index.ts': {} })).toThrow(/flowCplug/);
    expect(buildShipList({})).toEqual([]);
  });
});
