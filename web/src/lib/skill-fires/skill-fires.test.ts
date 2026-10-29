import { expect, test } from 'vitest';
import { agoText, emptyMessage, type SessionSkillFires } from './skill-fires';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const NOW = Date.parse('2026-09-28T10:10:00Z');

test('the ago words and the empty sentences', () => {
  expect(agoText('2026-09-28T10:05:00Z', NOW)).toBe('5m ago');
  expect(agoText('2026-09-28T07:10:00Z', NOW)).toBe('3h ago');
  expect(agoText('nope', NOW)).toBeNull();
  const base: SessionSkillFires = { state: 'measured', fired: 0, recent: [] };
  expect(emptyMessage(base)).toBe('this conversation has used no skills');
  expect(emptyMessage({ ...base, state: 'unsupported', fired: null })).toBe('this agent records no skill use');
  expect(emptyMessage({ ...base, state: 'not_measured', fired: null })).toBe('skill use could not be measured');
});
