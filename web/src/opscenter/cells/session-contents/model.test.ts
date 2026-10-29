import { describe, expect, test } from 'vitest';
import { SCOPES, accountOf, detailBeyondLines, inScope, itemScopeIcon, scopeFilterOf, shownSections, showEmptyOf, visibleItems } from './model';
import type { ContentsItem, ContentsSection } from './types';

const item = (name: string, scope: string, path: string | null = null, description = ''): ContentsItem =>
  ({ name, scope, path, description, detail: '', lines: null, open_root: null, open_path: null, status: 'available' });

describe('scope', () => {
  test('the option group lists local, global, all in that order', () => {
    expect([...SCOPES]).toEqual(['local', 'global', 'all']);
  });

  test('each item scope has its own icon; an unknown one falls back to the globe', () => {
    expect(['project', 'global', 'plugin', 'odd'].map(itemScopeIcon)).toEqual(['folder', 'globe', 'plug', 'globe']);
  });

  test('a stored value that is not a filter reads as all', () => {
    expect([scopeFilterOf('local'), scopeFilterOf('nope'), scopeFilterOf(undefined), scopeFilterOf(3)]).toEqual(['local', 'all', 'all', 'all']);
  });

  test('local is the project, global is the account and its plugins, all is everything', () => {
    expect(['global', 'project', 'plugin'].map((s) => inScope(s, 'local'))).toEqual([false, true, false]);
    expect(['global', 'project', 'plugin'].map((s) => inScope(s, 'global'))).toEqual([true, false, true]);
    expect(['global', 'project', 'plugin'].map((s) => inScope(s, 'all'))).toEqual([true, true, true]);
  });
});

describe('the text filter', () => {
  const items = [item('CLAUDE.md', 'global', '/cfg/CLAUDE.md'), item('deploy', 'project', '/w/.claude/commands/deploy.md', 'ship it')];

  test('matches name, path and description, case blind and trimmed', () => {
    expect(visibleItems(items, 'all', '  CLAUDE.MD ').map((i) => i.name)).toEqual(['CLAUDE.md']);
    expect(visibleItems(items, 'all', 'commands/').map((i) => i.name)).toEqual(['deploy']);
    expect(visibleItems(items, 'all', 'SHIP').map((i) => i.name)).toEqual(['deploy']);
  });

  test('applies the scope filter first', () => {
    expect(visibleItems(items, 'local', '').map((i) => i.name)).toEqual(['deploy']);
    expect(visibleItems(items, 'local', 'claude.md')).toEqual([]);
  });
});

describe('the account name', () => {
  test('is the config folder name, or default for the harness own dot folder', () => {
    expect(accountOf('/Users/a/.carnivore/accounts/joe-imc/')).toBe('joe-imc');
    expect(accountOf('/Users/a/.claude')).toBe('default');
    expect(accountOf('')).toBe('default');
  });
});

describe('empty sections', () => {
  const sections: ContentsSection[] = [
    { kind: 'instructions', truncated: false, items: [item('CLAUDE.md', 'global', '/cfg/CLAUDE.md')] },
    { kind: 'skills', truncated: false, items: [item('pdf', 'plugin', '/p/pdf.md')] },
    { kind: 'plugins', truncated: false, items: [] },
  ];
  const kinds = (shown: ReturnType<typeof shownSections>): string[] => shown.map((one) => one.section.kind);

  test('a stored value that is not a boolean shows them', () => {
    expect([showEmptyOf(false), showEmptyOf(true), showEmptyOf('no'), showEmptyOf(undefined)]).toEqual([false, true, true, true]);
  });

  test('showing keeps every section; hiding drops those with a count of 0', () => {
    expect(kinds(shownSections(sections, 'all', '', true))).toEqual(['instructions', 'skills', 'plugins']);
    expect(kinds(shownSections(sections, 'all', '', false))).toEqual(['instructions', 'skills']);
  });

  test('with filter text, hiding also drops the sections the text emptied; showing keeps them at 0', () => {
    expect(kinds(shownSections(sections, 'all', 'claude', false))).toEqual(['instructions']);
    expect(kinds(shownSections(sections, 'all', 'claude', true))).toEqual(['instructions', 'skills', 'plugins']);
  });

  test('the scope filter counts too: a section with nothing in this scope is dropped', () => {
    expect(kinds(shownSections(sections, 'local', '', false))).toEqual([]);
  });
});

describe('the details line beyond the line count', () => {
  const one = (over: Partial<ContentsItem>): ContentsItem => ({ name: 'a.md', scope: 'project', path: '/a.md', description: '', detail: '', lines: 19, status: 'loaded', ...over }) as ContentsItem;
  test('a bare line count is dropped, a trailing note is kept, an item with no lines keeps its detail', () => {
    expect(detailBeyondLines(one({ detail: '19 lines' }))).toBe('');
    expect(detailBeyondLines(one({ detail: '19 lines, imported by CLAUDE.md' }))).toBe('imported by CLAUDE.md');
    expect(detailBeyondLines(one({ lines: null, detail: 'model x' }))).toBe('model x');
  });
});
