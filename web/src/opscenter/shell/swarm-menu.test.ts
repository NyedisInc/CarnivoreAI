import { expect, test } from 'vitest';
import { icons } from '../ui/icons';
import { taskManagerTab } from '../../cplugs/huddle/task-manager-tab';

test('the swarm tab uses the alpha-over-two icon', () => {
  expect(taskManagerTab.icon).toBe('swarm');
  expect(icons['swarm']).toContain('<rect x="7" y="2.5" width="10" height="8.5" rx="2"/>');
});
