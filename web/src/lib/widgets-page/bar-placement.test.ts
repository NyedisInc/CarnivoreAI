import { describe, expect, test } from 'vitest';
import { barActionsFor, restorePlan, writtenRails, type RailSnap } from './bar-placement';
import type { RailLayout } from '../session-rail/rail-sections';

const notes = { widget: 'core.notes', look: null };
const files = { widget: 'core.files', look: null };
const layout = (...items: (typeof notes)[]): RailLayout => ({ sections: [items], ratio: 0.5 });

describe('barActionsFor', () => {
    test('a widget in no bar can be added to either', () => {
        expect(barActionsFor('core.notes', [files], [])).toEqual({
            status: { kind: 'none' },
            actions: [{ kind: 'add', edge: 'side' }, { kind: 'add', edge: 'bottom' }],
        });
    });

    test('a widget in one bar moves to the other or comes out of its own', () => {
        expect(barActionsFor('core.notes', [notes], []).actions).toEqual([{ kind: 'move', edge: 'bottom' }, { kind: 'take_out', edge: 'side' }]);
        expect(barActionsFor('core.notes', [], [notes]).actions).toEqual([{ kind: 'move', edge: 'side' }, { kind: 'take_out', edge: 'bottom' }]);
    });

    test('a widget in more than one place is left to edit layout', () => {
        expect(barActionsFor('core.notes', [notes], [notes])).toEqual({ status: { kind: 'many', count: 2 }, actions: [] });
    });
});

describe('writtenRails and restorePlan', () => {
    const before: RailSnap = { side: layout(notes), bottom: null };
    const after: RailSnap = { side: layout(), bottom: layout(notes) };

    test('names the rails whose arrangement changed, and none when nothing did', () => {
        expect(writtenRails(before, after)).toEqual(['side', 'bottom']);
        expect(writtenRails(before, before)).toEqual([]);
    });

    test('an undo removes the widget first, so a partial failure can only drop it', () => {
        expect(restorePlan(['side', 'bottom'], before, after)).toEqual(['bottom', 'side']);
    });
});
