import { describe, expect, it } from 'vitest';
import { ACTIONS } from '../../../../client/js/keymap/actions.js';
import { APP_CHORDS } from './chords';
import { effectiveAppChords, registryId } from './effective-chords';
import { matches, pick } from './router';

describe('the app chords with overrides laid over them', () => {
    it('with nothing stored the table is the built one', () => {
        expect(effectiveAppChords(APP_CHORDS, {}, 'mac')).toEqual([...APP_CHORDS]);
    });

    it('an overridden action takes its stored chord and the built one stops firing', () => {
        const table = effectiveAppChords(APP_CHORDS, { mac: { 'history.back': ['shift+cmd+arrowleft'] } }, 'mac');
        expect(pick(table, { key: '[', metaKey: true })).toBeNull();
        const hit = pick(table, { key: 'ArrowLeft', metaKey: true, shiftKey: true });
        expect(hit?.id).toBe('history.back');
        expect(hit?.run).toBe(APP_CHORDS.find((c) => c.id === 'history.back')?.run);
    });

    it('an unbound action ([]) has no entry, and an untouched one keeps its own', () => {
        const table = effectiveAppChords(APP_CHORDS, { mac: { 'history.forward': [] } }, 'mac');
        expect(table.some((c) => c.id === 'history.forward')).toBe(false);
        expect(table.some((c) => c.id === 'history.back')).toBe(true);
    });

    it('the other keyboard has its own overrides, and the palette is one action with two built entries', () => {
        const table = effectiveAppChords(APP_CHORDS, { other: { 'palette.open': ['ctrl+alt+p'], 'history.back': ['ctrl+shift+arrowleft'] } }, 'other');
        expect(table.filter((c) => registryId(c.id) === 'palette.open')).toHaveLength(1);
        expect(pick(table, { key: 'p', code: 'KeyP', ctrlKey: true, altKey: true })?.id).toBe('palette.open.other');
        expect(pick(table, { key: 'ArrowLeft', ctrlKey: true, shiftKey: true })?.id).toBe('history.back');
        expect(effectiveAppChords(APP_CHORDS, { mac: { 'history.back': [] } }, 'other')).toEqual([...APP_CHORDS]);
    });

    it('Alt matches the physical key, since Option composes another character on a Mac', () => {
        const table = effectiveAppChords(APP_CHORDS, { mac: { 'palette.actions': ['alt+cmd+j'] } }, 'mac');
        expect(pick(table, { key: '∆', code: 'KeyJ', altKey: true, metaKey: true })?.id).toBe('palette.actions');
    });

    it('a symbol key fires with or without shift', () => {
        const table = effectiveAppChords(APP_CHORDS, { mac: { 'history.back': ['cmd+?'] } }, 'mac');
        const chord = table.find((c) => c.id === 'history.back')!;
        expect(matches(chord, { key: '?', metaKey: true, shiftKey: true })).toBe(true);
        expect(matches(chord, { key: '?', metaKey: true })).toBe(true);
    });
});

describe('rebindable is claimed only by actions this router reads', () => {
    it('the registry marks exactly the app chords the router owns', () => {
        const wired = [...new Set(APP_CHORDS.map((c) => registryId(c.id)))].sort();
        const marked = ACTIONS.filter((a: { rebindable: boolean }) => a.rebindable).map((a: { id: string }) => a.id).sort();
        expect(marked).toEqual(wired);
    });

    it('each marked action really answers an override (a change is never offered that does nothing)', () => {
        for (const id of ACTIONS.filter((a: { rebindable: boolean }) => a.rebindable).map((a: { id: string }) => a.id)) {
            const none = effectiveAppChords(APP_CHORDS, { mac: { [id]: [] } }, 'mac');
            expect(none.length, id).toBeLessThan(APP_CHORDS.length);
        }
    });
});
