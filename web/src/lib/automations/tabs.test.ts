import { expect, test } from 'vitest';
import { AUTOMATIONS_TABS, DEFAULT_TAB, effectiveTab } from './tabs';

test('the tabs are automations, sessions and advanced; huddle and junk fall back to the first', () => {
  expect([...AUTOMATIONS_TABS]).toEqual(['automations', 'sessions', 'advanced']);
  expect(effectiveTab('advanced')).toBe('advanced');
  expect(effectiveTab('sessions')).toBe('sessions');
  expect(effectiveTab('huddle')).toBe(DEFAULT_TAB);
  expect(effectiveTab('')).toBe('automations');
});
