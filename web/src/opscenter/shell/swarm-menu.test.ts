import { expect, test } from 'vitest';
import { RAIL_DESTINATIONS } from './rail-items';
import { icons } from '../ui/icons';
import { taskManagerTab } from '../../cplugs/huddle/task-manager-tab';

test('the swarm menu row sits directly after settings and uses the alpha-over-two icon', () => {
  const ids = RAIL_DESTINATIONS.map((i) => i.id);
  expect(ids[ids.indexOf('settings') + 1]).toBe('huddle');
  expect(RAIL_DESTINATIONS.find((i) => i.id === 'huddle')?.icon).toBe('swarm');
  expect(taskManagerTab.icon).toBe('swarm');
  expect(icons['swarm']).toContain('<rect x="7" y="2.5" width="10" height="8.5" rx="2"/>');
});
