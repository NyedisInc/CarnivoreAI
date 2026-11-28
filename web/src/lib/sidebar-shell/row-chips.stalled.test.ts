import { expect, test } from 'vitest';
import { shellsIconPlan } from './row-chips';
import type { SidebarRow } from './legacy';

test('stalled_agents alone draws the shells icon with the hint as its title', () => {
  const plan = shellsIconPlan({ stalled_agents: 1 } as unknown as SidebarRow);
  expect(plan?.attrs.title).toBe('1 background agent stopped reporting');
});

test('no count and no parked reason still draws nothing, and a count rides after the shells text', () => {
  expect(shellsIconPlan({ stalled_agents: 0 } as unknown as SidebarRow)).toBeNull();
  const both = shellsIconPlan({ background_open: 2, stalled_agents: 2 } as unknown as SidebarRow);
  expect(both?.attrs.title).toContain('; 2 background agents stopped reporting');
});
