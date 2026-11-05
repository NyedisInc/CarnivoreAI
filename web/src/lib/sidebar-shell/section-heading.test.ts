/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { sectionIdOfKey, sectionTargetOf } from './section-heading';

function rowIn(key: string, attrs: Record<string, string>, lead = false): Element {
    const wrapper = document.createElement('div');
    for (const [name, value] of Object.entries(attrs)) wrapper.setAttribute(name, value);
    wrapper.innerHTML = `${lead ? '<div class="lead"></div>' : ''}<div class="session-sidebar-group__headerrow"><button data-group-toggle="${key}"></button></div>`;
    return wrapper.querySelector('.session-sidebar-group__headerrow')!;
}

describe('which heading rows are section headings', () => {
    it('the top row of a data-section wrapper is the section it names', () => {
        const row = rowIn('terminals', { 'data-section': 'terminals' });
        expect(sectionTargetOf(row)).toEqual({ key: 'terminals', row });
    });

    it('a heading carrying a section key but sitting in no section wrapper is no section (the guard)', () => {
        expect(sectionTargetOf(rowIn('terminals', { 'data-group': 'terminals' }))).toBeNull();
    });

    it('a row that is not the first child of its section wrapper is no section', () => {
        expect(sectionTargetOf(rowIn('terminals', { 'data-section': 'terminals' }, true))).toBeNull();
    });

    it('FILES is its own section: the top row of its data-section wrapper', () => {
        const row = rowIn('files', { 'data-section': 'files' });
        expect(sectionTargetOf(row)).toEqual({ key: 'files', row });
    });

    it('a key that names no section is none, even at the top of a section wrapper', () => {
        expect(sectionTargetOf(rowIn('p:5', { 'data-section': 'terminals' }))).toBeNull();
    });

    it('FILES is its own section id; a nested key is no section id', () => {
        expect(sectionIdOfKey('files')).toBe('files');
        expect(sectionIdOfKey('companies')).toBe('companies');
        expect(sectionIdOfKey('g:abc')).toBeNull();
    });
});
