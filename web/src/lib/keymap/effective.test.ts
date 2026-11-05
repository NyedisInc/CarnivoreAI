import { expect, test } from 'vitest';
import { ACTIONS } from '../../../../client/js/keymap/actions.js';
import { chordFromEvent, matchesChord, normalize } from '../../../../client/js/keymap/chord.js';
import { conflicts, findByChord, findByName } from '../../../../client/js/keymap/effective.js';
import { scopesOverlap } from '../../../../client/js/keymap/scopes.js';
import { isGestureRebindable, keyboardFamily } from '../../../../client/js/keymap/policy.js';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';

const t = (key: string): string => (enCatalog as Record<string, string>)[key] ?? key;
const ids = (list: readonly { id: string }[]): string[] => list.map((a) => a.id);

test('find by name matches a label, a chord and a gesture', () => {
    expect(ids(findByName(ACTIONS, 'zoom the terminal', 'mac', t))).toContain('terminal.zoom.toggle');
    expect(ids(findByName(ACTIONS, 'cmd k', 'mac', t))).toContain('palette.open');
    expect(ids(findByName(ACTIONS, 'middle', 'mac', t))).toContain('mouse.tab.close');
    expect(findByName(ACTIONS, 'zzzz no such thing', 'mac', t)).toEqual([]);
    expect(findByName(ACTIONS, '  ', 'mac', t)).toHaveLength(ACTIONS.length);
});

test('find by pressing lists every action on the chord, on the right keyboard', () => {
    expect(ids(findByChord(ACTIONS, 'cmd+k', 'mac'))).toEqual(['palette.open']);
    expect(findByChord(ACTIONS, 'cmd+k', 'other')).toEqual([]);
    expect(ids(findByChord(ACTIONS, 'ctrl+shift+k', 'other'))).toEqual(['palette.open']);
    expect(ids(findByChord(ACTIONS, 'enter', 'mac'))).toEqual(expect.arrayContaining(['catalog.open', 'review.open', 'terminal.search.next']));
});

test('an event becomes the chord it is, Alt by physical key and a symbol without Shift', () => {
    expect(chordFromEvent({ key: 'K', code: 'KeyK', metaKey: true, shiftKey: true })).toBe('shift+cmd+k');
    expect(chordFromEvent({ key: 'å', code: 'KeyA', altKey: true })).toBe('alt+a');
    expect(chordFromEvent({ key: '?', shiftKey: true })).toBe('?');
    expect(chordFromEvent({ key: 'Shift', shiftKey: true })).toBeNull();
    expect(matchesChord('Cmd+K', { key: 'k', metaKey: true })).toBe(true);
    expect(normalize('Cmd+Plus')).toBe('cmd++');
});

test('a clash needs scopes that can be live together, and a planted one is found', () => {
    expect(scopesOverlap('list:feed', 'list:review')).toBe(false);
    expect(scopesOverlap('global', 'list:feed')).toBe(true);
    expect(scopesOverlap('menu', 'global', false)).toBe(false);
    const planted = { mac: { 'palette.actions': ['cmd+k'] } };
    expect(conflicts(ACTIONS, 'mac', planted)).toEqual([{ chord: 'cmd+k', a: 'palette.open', b: 'palette.actions' }]);
});

test('the open rulings are data: separate families, middle click the only rebindable gesture', () => {
    expect(keyboardFamily('MacIntel')).toBe('mac');
    expect(keyboardFamily('Win32')).toBe('other');
    expect(isGestureRebindable('middle')).toBe(true);
    expect(isGestureRebindable('double')).toBe(false);
});
