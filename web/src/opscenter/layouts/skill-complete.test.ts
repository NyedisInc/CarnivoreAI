import { expect, test } from 'vitest';
import { flushSync } from 'svelte';
import type { LayoutSkill } from './api';
import { filterSkills, typing } from './skill-complete';
import { SkillComplete } from './skill-complete.svelte';

const SKILLS: LayoutSkill[] = [
  { name: 'deploy', description: 'ship it', scope: 'global' },
  { name: 'review', description: 'review a diff', scope: 'global' },
  { name: 'pre-review', description: 'before review', scope: 'project' },
  { name: 'work', description: 'claim an issue, then deploy', scope: 'global' },
];

test('only a line that starts with a sigil and has no space is a skill being typed', () => {
  expect(typing('/rev')).toEqual({ sigil: '/', query: 'rev' });
  expect(typing('$')).toEqual({ sigil: '$', query: '' });
  expect(typing('/rev x')).toBeNull();
  expect(typing('git /rev')).toBeNull();
});

test('filter ranks name prefix, then name contains, then description', () => {
  expect(filterSkills(SKILLS, 'rev').map((s) => s.name)).toEqual(['review', 'pre-review']);
  expect(filterSkills(SKILLS, 'deploy').map((s) => s.name)).toEqual(['deploy', 'work']);
  expect(filterSkills(SKILLS, 'zzz')).toEqual([]);
});

test('keys walk, accept with the typed sigil, and escape closes until the text changes', async () => {
  let box = '';
  const c = new SkillComplete({ layoutUuid: () => 'L1', put: (t) => { box = t; }, load: async () => SKILLS });
  c.update('$re', true);
  await Promise.resolve(); await Promise.resolve();
  flushSync();
  expect(c.rows.map((s) => s.name)).toEqual(['review', 'pre-review']);
  expect(c.key('ArrowDown')).toBe(true);
  expect(c.active).toBe(1);
  expect(c.key('Escape')).toBe(true);
  c.update('$re', true);
  expect(c.open).toBe(false);
  c.update('$rev', true);
  expect(c.open).toBe(true);
  expect(c.key('Tab')).toBe(true);
  expect(box).toBe('$review ');
  expect(c.open).toBe(false);
  expect(c.key('Enter')).toBe(false);
});

test('search mode never opens it', () => {
  const c = new SkillComplete({ layoutUuid: () => 'L1', put: () => {}, load: async () => SKILLS });
  c.update('/re', false);
  expect(c.open).toBe(false);
});
