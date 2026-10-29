import { describe, expect, it } from 'vitest';
import { isFirstParty, offEntries, shownEntries, type RequiredEntry } from './required-skills';

const entry = (state: RequiredEntry['state']): RequiredEntry => ({ item_id: 'carnivore/huddle', required: true, state, install_id: null, local_edits: null });

describe('required skills strip', () => {
    it('draws blocked and locally edited entries only', () => {
        expect(shownEntries([entry('blocked'), { ...entry('installed'), local_edits: true }])).toHaveLength(2);
        expect(shownEntries([entry('installed'), { ...entry('installed'), local_edits: false }, entry('available'), entry('declined')])).toEqual([]);
    });
    it('lists a not installed carnivore skill as an off card, never a blocked or installed one', () => {
        const optional = (state: RequiredEntry['state']): RequiredEntry => ({ ...entry(state), item_id: 'carnivore/widget-builder', required: false });
        expect(offEntries([optional('available'), optional('declined')])).toHaveLength(2);
        expect(offEntries([optional('blocked'), optional('installed')])).toEqual([]);
        expect(shownEntries([optional('blocked')])).toEqual([]);
    });
    it('badges only carnivore items', () => {
        expect(isFirstParty('carnivore/huddle')).toBe(true);
        expect(isFirstParty('acme/sme')).toBe(false);
        expect(isFirstParty(undefined)).toBe(false);
    });
});
