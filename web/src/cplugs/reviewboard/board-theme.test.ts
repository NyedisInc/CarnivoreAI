/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { effectiveTheme, flatChoices, readThemeChoice, registerThemeSource, themeGroups, THEME_KEY, tokensFor, writeThemeChoice } from './board-theme';

const choices = [{ id: 'carnivore', name: 'Carnivore' }, { id: 'dracula', name: 'Dracula' }];

afterEach(() => localStorage.clear());

describe('effectiveTheme', () => {
  it('follows the app until a theme is chosen', () => expect(effectiveTheme('', choices, 'carnivore')).toBe('carnivore'));
  it('wears the chosen theme', () => expect(effectiveTheme('dracula', choices, 'carnivore')).toBe('dracula'));
  it('falls back to the app theme when the chosen one no longer exists', () => expect(effectiveTheme('gone', choices, 'carnivore')).toBe('carnivore'));
  it('is null when nothing is known', () => expect(effectiveTheme('', [], null)).toBeNull());
});

describe('the remembered choice', () => {
  it('is kept per device and forgotten with an empty id', () => {
    expect(readThemeChoice()).toBe('');
    writeThemeChoice('dracula');
    expect(localStorage.getItem(THEME_KEY)).toBe('dracula');
    expect(readThemeChoice()).toBe('dracula');
    writeThemeChoice('');
    expect(localStorage.getItem(THEME_KEY)).toBeNull();
  });
});

describe('theme sources', () => {
  const source = (id: string, ids: string[]) => ({
    id, label: id, list: () => ids.map((i) => ({ id: i, name: i })), tokens: (i: string) => (ids.includes(i) ? { '--oc-orange': `from-${id}` } : null),
  });

  it('lists a registered source after the app registry and removes it again', () => {
    const remove = registerThemeSource(source('mine', ['x']));
    expect(themeGroups().map((g) => g.source.id)).toContain('mine');
    remove();
    expect(themeGroups().map((g) => g.source.id)).not.toContain('mine');
  });

  it('replaces a source registered under the same id', () => {
    const first = registerThemeSource(source('mine', ['a']));
    const second = registerThemeSource(source('mine', ['b']));
    expect(flatChoices(themeGroups()).map((c) => c.id)).toEqual(['b']);
    second();
    first();
  });

  it('leaves out an empty source, and answers a palette from the first source that has the id', () => {
    const one = registerThemeSource(source('one', ['shared', 'a']));
    const two = registerThemeSource(source('two', ['shared', 'b']));
    const empty = registerThemeSource(source('empty', []));
    expect(themeGroups().map((g) => g.source.id)).toEqual(['one', 'two']);
    expect(flatChoices(themeGroups()).map((c) => c.id)).toEqual(['shared', 'a', 'b']);
    expect(tokensFor('shared')).toEqual({ '--oc-orange': 'from-one' });
    expect(tokensFor('b')).toEqual({ '--oc-orange': 'from-two' });
    expect(tokensFor('nope')).toBeNull();
    for (const remove of [one, two, empty]) remove();
  });
});
