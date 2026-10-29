import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

import { kindIcon } from '../../lib/catalog/card';
import { META, TERMINAL_META } from '../engine/meta';
import { icons } from './icons';
import { fixtureInventory } from '../../lib/skills-page/skills-fixtures';
import { TOOLBAR_ITEMS } from '../cells/terminal-live/toolbar';
import { toItems } from '../../lib/skills-page/skills-model';

const MOD_MARKUP = "<path d=\"M7 4H6a2 2 0 0 0-2 2v4l-2 2 2 2v4a2 2 0 0 0 2 2h1M17 4h1a2 2 0 0 1 2 2v4l2 2-2 2v4a2 2 0 0 1-2 2h-1\"/><rect x=\"9\" y=\"9\" width=\"6\" height=\"6\" rx=\"1\"/>";
const SKILL_MARKUP = "<path d=\"M12 4.5 22 9.5l-10 5-10-5Z\"/><path d=\"M6 11.5v4.5c0 1.5 3 3 6 3s6-1.5 6-3v-4.5M20 10.5v5\"/>";

describe('mods and skills glyphs', () => {
  test('the catalog kinds draw the new glyphs, plugins keep the plug', () => {
    expect(kindIcon('mod')).toBe('mod');
    expect(kindIcon('skill')).toBe('skill');
    expect(kindIcon('plugin')).toBe('plug');
  });

  test('both markups are the picked ones', () => {
    expect(icons.mod).toBe(MOD_MARKUP);
    expect(icons.skill).toBe(SKILL_MARKUP);
  });

  test('the skills widget draws the skill glyph, shell and terminal keep the terminal glyph', () => {
    expect(META.skills.icon).toBe('skill');
    expect(TERMINAL_META.icon).toBe('terminal');
  });

  test('every skills page row stands for a skill, so it draws the skill glyph', () => {
    const global = { id: 'global', kind: 'global' as const, label: 'global', projectPath: null, profile: null };
    const items = toItems(fixtureInventory(), global, (key: string) => key);
    expect(items.length).toBeGreaterThan(1);
    for (const item of items) expect(item.icon).toBe('skill');
  });

  test('the census rows and the terminal skills entry draw the skill glyph', () => {
    const files = ['CensusTab.svelte'];
    for (const f of files) {
      const path = new URL(`../../lib/skills-page/${f}`, import.meta.url);
      expect(readFileSync(path, 'utf8')).toMatch(/icon: 'skill'/);
    }
    expect(TOOLBAR_ITEMS.find((item) => item.id === 'skills')?.icon).toBe('skill');
  });
});
