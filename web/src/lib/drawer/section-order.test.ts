import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { isBrowserBand, pageSectionIds, pageSectionOf, pageSectionRows } from './bucketing';
import { PAGE_SECTION_SLOT, pageSectionMeta, registerPageSections, resetPageSections } from './page-sections';
import { isFoldKey } from './store-keys';
import {
    DEFAULT_SECTION_ORDER, moveSection, previewOrder, resolveSectionOrder, sectionOfBand, setPreviewOrder, stepSection,
    type SectionId,
} from './section-order';

describe('resolveSectionOrder', () => {
    it('is the default with nothing stored', () => {
        expect(resolveSectionOrder(undefined)).toEqual([...DEFAULT_SECTION_ORDER]);
        expect(resolveSectionOrder(null)).toEqual([...DEFAULT_SECTION_ORDER]);
        expect(DEFAULT_SECTION_ORDER.length).toBe(9);
    });

    it('puts a section missing from an old stored order right after its default predecessor', () => {
        const old = ['browsers', 'terminals', 'rogue', 'companies', 'groups', 'layouts', 'pinned'];
        expect(resolveSectionOrder(old)).toEqual(['browsers', 'review', 'pack', 'terminals', 'rogue', 'companies', 'groups', 'layouts', 'pinned']);
        expect(resolveSectionOrder(['layouts', 'groups', 'companies', 'rogue', 'terminals', 'browsers', 'pack'])[0]).toBe('pinned');
    });

    it('drops unknown and repeated ids', () => {
        const got = resolveSectionOrder(['pack', 'nope', 'pack', 'pinned', 7 as unknown as string]);
        expect(got.filter((x) => x === 'pack').length).toBe(1);
        expect(got).not.toContain('nope' as SectionId);
        expect(got.length).toBe(9);
    });
});

describe('a stored order and a section it does not name (#1863)', () => {
    it('a section missing from the stored order joins right after its default predecessor', () => {
        const got = resolveSectionOrder(['terminals', 'pinned', 'layouts', 'companies', 'browsers', 'review', 'pack']);
        expect(got).toEqual(['terminals', 'pinned', 'layouts', 'groups', 'companies', 'rogue', 'browsers', 'review', 'pack']);
    });

    it('a stored order survives a section this build added: every stored id keeps its relative order', () => {
        const stored = ['pack', 'review', 'browsers', 'terminals', 'rogue', 'companies', 'layouts', 'pinned'];
        const got = resolveSectionOrder(stored);
        expect(got.filter((id) => stored.indexOf(id) !== -1)).toEqual(stored);
        expect(got.indexOf('groups')).toBe(got.indexOf('layouts') + 1);
        expect(stored.length).toBe(8);
        expect(resolveSectionOrder(got)).toEqual(got);
    });

    it('moving GROUPS (the block) leaves every other section in place', () => {
        const order = resolveSectionOrder(null);
        const moved = moveSection(order, 'groups', 'pinned', order);
        expect(moved[0]).toBe('groups');
        expect(moved.filter((x) => x !== 'groups')).toEqual(order.filter((x) => x !== 'groups'));
    });
});

describe('moveSection', () => {
    const order: SectionId[] = ['pinned', 'layouts', 'groups', 'companies', 'rogue', 'terminals', 'browsers', 'pack'];

    it('lands before the section it was dropped above, hidden sections keeping their place', () => {
        const visible: SectionId[] = ['pinned', 'groups', 'companies', 'terminals', 'browsers', 'pack'];
        expect(moveSection(order, 'browsers', 'pinned', visible)).toEqual(
            ['browsers', 'pinned', 'layouts', 'groups', 'companies', 'rogue', 'terminals', 'pack'],
        );
        expect(moveSection(order, 'pinned', 'terminals', visible)).toEqual(
            ['layouts', 'groups', 'companies', 'rogue', 'pinned', 'terminals', 'browsers', 'pack'],
        );
    });

    it('null puts it after the last VISIBLE section and leaves a trailing hidden one alone', () => {
        const visible: SectionId[] = ['pinned', 'groups', 'browsers'];
        expect(moveSection(order, 'pinned', null, visible)).toEqual(
            ['layouts', 'groups', 'companies', 'rogue', 'terminals', 'browsers', 'pinned', 'pack'],
        );
    });

    it('returns the same order for a no-op move', () => {
        expect(moveSection(order, 'pinned', 'layouts', order)).toEqual(order);
        expect(moveSection(order, 'pack', null, order)).toEqual(order);
        expect(moveSection(order, 'pinned', 'pinned', order)).toEqual(order);
    });
});

describe('stepSection', () => {
    const order: SectionId[] = ['pinned', 'layouts', 'groups', 'terminals'];
    it('steps one visible slot and refuses at an edge', () => {
        expect(stepSection(order, ['pinned', 'groups', 'terminals'], 'pinned', 1)).toEqual(['layouts', 'groups', 'pinned', 'terminals']);
        expect(stepSection(order, order, 'terminals', -1)).toEqual(['pinned', 'layouts', 'terminals', 'groups']);
        expect(stepSection(order, order, 'pinned', -1)).toBeNull();
        expect(stepSection(order, order, 'terminals', 1)).toBeNull();
        expect(stepSection(order, ['pinned'], 'pinned', 1)).toBeNull();
    });
});

describe('sectionOfBand and the preview', () => {
    afterEach(() => setPreviewOrder(null));
    it('maps band keys to unit ids', () => {
        expect(sectionOfBand('groups')).toBe('groups');
        expect(sectionOfBand('g:3f2a')).toBeNull();
        for (const k of ['pinned', 'layouts', 'rogue', 'terminals', 'browsers']) expect(sectionOfBand(k)).toBe(k);
        expect(sectionOfBand('p:7')).toBeNull();
        expect(sectionOfBand('p:7:agents')).toBeNull();
    });
    it('keeps a copy of the preview order', () => {
        const o: SectionId[] = ['pack', 'pinned'];
        setPreviewOrder(o);
        o.push('layouts');
        expect(previewOrder()).toEqual(['pack', 'pinned']);
        setPreviewOrder(null);
        expect(previewOrder()).toBeNull();
    });
});

describe('a plugin page section', () => {
    const board = { name: 'browser:0123456789abcdef', kind: 'browser', page: true, section: 'review' };
    const other = { name: 'browser:1111111111111111', kind: 'browser', page: true, section: 'notes' };
    const site = { name: 'browser:fedcba9876543210', kind: 'browser' };
    const artifact = { name: 'browser:00112233445566ff', kind: 'browser', page: true, section: null };
    const agentRow = { name: 'cloude_a', kind: 'agent', section: 'review' };

    beforeEach(() => {
        resetPageSections();
        registerPageSections([{ id: 'review', labelKey: 'cplug.reviewboard.page_section', icon: 'eye' }]);
    });
    afterEach(() => resetPageSections());

    it('files a page row under the section it names and every other browser row under BROWSERS', () => {
        expect(pageSectionOf(board)).toBe('review');
        expect(pageSectionOf(other)).toBe('notes');
        expect(isBrowserBand(board)).toBe(false);
        for (const row of [site, artifact]) {
            expect(pageSectionOf(row)).toBeNull();
            expect(isBrowserBand(row)).toBe(true);
        }
        expect(pageSectionOf(agentRow)).toBeNull();
    });

    it('makes one band per section id, in the order first seen, each holding only its own rows', () => {
        const rows = [board, site, other, { ...board, name: 'browser:2222222222222222' }];
        expect(pageSectionIds(rows)).toEqual(['review', 'notes']);
        expect(pageSectionRows(rows, 'review').map((r) => r.name)).toEqual([board.name, 'browser:2222222222222222']);
    });

    it('rides in the movable review slot, right after browsers by default, and its id is a fold key', () => {
        expect(sectionOfBand('review')).toBe(PAGE_SECTION_SLOT);
        expect(sectionOfBand('notes')).toBeNull();
        registerPageSections([{ id: 'notes', labelKey: 'cplug.notes.section', icon: 'note' }]);
        expect(sectionOfBand('notes')).toBe(PAGE_SECTION_SLOT);
        expect(DEFAULT_SECTION_ORDER.indexOf(PAGE_SECTION_SLOT)).toBe(DEFAULT_SECTION_ORDER.indexOf('browsers') + 1);
        expect(isFoldKey('review')).toBe(true);
        expect(isFoldKey('notes')).toBe(true);
    });

    it('lets two plugins share a section: the first declarer\'s label and icon win, whatever the order of the rest', () => {
        resetPageSections();
        registerPageSections([{ id: 'review', labelKey: 'cplug.flow.page_section', icon: 'eye' }]);
        registerPageSections([{ id: 'review', labelKey: 'cplug.reviewboard.page_section', icon: 'other' }]);
        expect(pageSectionMeta('review')).toEqual({ id: 'review', labelKey: 'cplug.flow.page_section', icon: 'eye' });
    });

    it('keeps a saved review fold and slot before any plugin has registered', () => {
        resetPageSections();
        expect(isFoldKey('review')).toBe(true);
        expect(sectionOfBand('review')).toBe('review');
    });
});
