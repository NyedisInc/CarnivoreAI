import { expect, test } from 'vitest';
import { ACTIONS, CATEGORIES } from '../../../../client/js/keymap/actions.js';
import { caps, formatChord } from '../../../../client/js/keymap/chord.js';
import { capRows, conflicts } from '../../../../client/js/keymap/effective.js';
import { isScope } from '../../../../client/js/keymap/scopes.js';
import { GESTURES, KEYBOARD_FAMILIES } from '../../../../client/js/keymap/policy.js';
import { LETTERS } from '../../../../client/js/menu-keys.js';
import { menuActionId } from '../../../../client/js/keymap/menu-actions.js';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { keySections } from '../info-pages/key-bindings';
import { APP_CHORDS } from '../app-keys/chords';

const catalog = enCatalog as Record<string, string>;
const byId = new Map(ACTIONS.map((a) => [a.id, a]));

const tokens = (text: string): string => text.split(' ').filter(Boolean).sort().join(' ');

function alternatives(keys: string): string[] {
    if (keys === 'cmd 1 to 8') return [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `cmd ${n}`);
    if (keys === 'j  k') return ['j', 'k'];
    return keys.split(' / ');
}

function defaultsFor(labelKey: string): Set<string> {
    const out = new Set<string>();
    for (const a of ACTIONS.filter((x) => x.labelKey === labelKey || x.altLabelKeys.includes(labelKey))) {
        for (const family of KEYBOARD_FAMILIES) for (const chord of a.keys[family as 'mac' | 'other']) out.add(tokens(formatChord(chord)));
    }
    return out;
}

test('every row the old shortcuts page returned is in the registry with the same default', () => {
    const rows = keySections().flatMap((s) => s.rows);
    expect(rows.length).toBeGreaterThan(30);
    for (const row of rows) {
        const have = defaultsFor(row.labelKey);
        for (const alt of alternatives(row.keys)) expect(have.has(tokens(alt)), `${row.labelKey}: ${alt}`).toBe(true);
    }
});

test('every APP_CHORDS id is in the registry with the same chord', () => {
    for (const c of APP_CHORDS) {
        const chord = [c.ctrl && 'ctrl', c.shift && 'shift', c.meta && 'cmd'].filter(Boolean).concat(c.key).join('+');
        const id = c.id === 'palette.open.other' ? 'palette.open' : c.id;
        const family = c.meta ? 'mac' : 'other';
        const action = byId.get(id);
        expect(action, c.id).toBeTruthy();
        expect(action!.keys[family], c.id).toContain(chord);
    }
});

test('every LETTERS entry is a menu action with the same letter', () => {
    for (const entry of LETTERS) {
        const action = byId.get(menuActionId(entry));
        expect(action, entry.meaning).toBeTruthy();
        expect(action!.keys.mac, entry.meaning).toEqual([entry.letter]);
        expect(action!.keys.other, entry.meaning).toEqual([entry.letter]);
    }
});

test('the registry is sound: unique ids, known scopes and categories, labels in the catalog', () => {
    expect(new Set(ACTIONS.map((a) => a.id)).size).toBe(ACTIONS.length);
    for (const a of ACTIONS) {
        expect(isScope(a.scope), `${a.id} scope ${a.scope}`).toBe(true);
        expect(CATEGORIES, a.id).toContain(a.category);
        for (const key of [a.labelKey, ...a.altLabelKeys, a.fixedKey]) expect(catalog[key], `${a.id}: ${key}`).toBeTruthy();
        for (const g of a.mouse) expect(GESTURES, a.id).toContain(g);
        expect(a.owner, a.id).toBeTruthy();
    }
    for (const c of CATEGORIES) expect(catalog[`keymap.category.${c}`], c).toBeTruthy();
});

test('no two shipped defaults clash on either keyboard family', () => {
    for (const family of KEYBOARD_FAMILIES) expect(conflicts(ACTIONS, family), family).toEqual([]);
});

test('every menu name has one catalog line and it is the letter registry\'s own meaning', () => {
    for (const entry of LETTERS) {
        expect(entry.name, entry.meaning).toMatch(/^[a-z0-9-]+$/);
        expect(catalog[`keymap.menu.${entry.name}`], entry.name).toBe(entry.meaning);
        expect(entry.meaning, entry.name).not.toMatch(/\*|-id\b/);
    }
    expect(new Set(LETTERS.map((e) => e.name)).size).toBe(LETTERS.length);
});

test('every action says which screen it belongs to, with its own words, and a gesture is never a keycap', () => {
    const screens = new Set<string>();
    for (const a of ACTIONS) {
        const key = `keymap.scope.${a.scope.replace(':', '.')}`;
        expect(catalog[key], `${a.id}: ${key}`).toBeTruthy();
        screens.add(key);
        for (const g of a.mouse) expect(catalog[`keymap.gesture.${g.replace('+', '_')}`], g).toBeTruthy();
        if (a.keys.mac.length + a.keys.other.length === 0) expect(a.mouse.length, a.id).toBeGreaterThan(0);
    }
    expect(screens.size).toBeGreaterThan(20);
    expect(capRows(byId.get('mouse.tab.close'), 'mac')).toEqual([]);
});

test('the bindings the first review found missing are listed, each on its own', () => {
    const want = ['palette.pick_1', 'palette.pick_2', 'palette.pick_5', 'palette.chip_remove', 'terminal.paste', 'desktop.role.copy', 'desktop.role.paste',
        'keybar.up', 'keybar.shifttab', 'keybar.stash', 'mouse.gutter.reset', 'mouse.drawer.reset', 'mouse.crosstalk.split.reset',
        'mouse.huddle.status_fold_all', 'mouse.swarm.open_terminal'];
    for (const id of want) expect(byId.has(id), id).toBe(true);
});

test('no two actions in the whole registry read the same words', () => {
    const seen = new Map<string, string>();
    for (const a of ACTIONS) {
        const words = catalog[a.labelKey] ?? a.labelKey;
        expect(seen.get(words), `${a.id} repeats the words of ${seen.get(words)}: "${words}"`).toBeUndefined();
        seen.set(words, a.id);
    }
});

test('a chord reads as keycaps and as text', () => {
    expect(caps('shift+cmd+enter')).toEqual(['shift', 'cmd', 'enter']);
    expect(formatChord('cmd+arrowup')).toBe('cmd up');
});
