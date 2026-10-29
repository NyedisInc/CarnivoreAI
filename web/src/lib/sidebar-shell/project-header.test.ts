/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { iconForBand, iconHtml, ledHtml, pickedIconHtml } from './project-header';

const g = globalThis as Record<string, unknown>;
afterEach(() => { delete g.SessionStatusSummary; delete g.CloudeGlyphs; });

describe('heading helpers', () => {
    it('the light draws only for a collapsed section with a non-browser row', () => {
        g.SessionStatusSummary = { summaryHtml: () => '<i></i>' };
        expect(ledHtml([{ kind: 'agent' }], false)).toBe('');
        expect(ledHtml([{ kind: 'agent' }], true, false)).toBe('');
        expect(ledHtml([{ kind: 'browser' }], true)).toBe('');
        expect(ledHtml([{ kind: 'agent' }], true)).toBe('<span class="session-sidebar-group__project-led"><i></i></span>');
    });
    it('the icon needs a name and a glyph table', () => {
        expect(iconHtml(null)).toBe('');
        expect(iconHtml('pin')).toBe('');
        g.CloudeGlyphs = { glyphSvg: (n: string, s: number) => `<svg data-n="${n}" data-s="${s}"></svg>` };
        expect(iconHtml('pin')).toContain('data-s="12"');
    });
    it('each band key wears its glyph', () => {
        expect(iconForBand('x', true)).toBe('folder');
        expect([iconForBand('pinned'), iconForBand('open'), iconForBand('sleeping'), iconForBand('terminals'),
            iconForBand('browsers'), iconForBand('files'), iconForBand('layouts'), iconForBand('nope')])
            .toEqual(['pin', 'bolt', 'sleeping-agent', 'terminal', 'globe', 'code', 'grid', null]);
    });
    it('a picked icon is only for a hand-made group', () => {
        expect(pickedIconHtml({ key: 'pinned', bandKind: 'pinned' })).toBe('');
    });
});
