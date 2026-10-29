/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fxHtml, nextStyle, styleAttrs } from './group-color-palette';
import { setDrawerEnv } from './env';
import * as GroupStore from './group-store';
import * as GroupColor from './group-color';

/** The drawer's repaint and groups re-read, observed (the popup imports them from the shell's interaction globals directly). */
const actions = vi.hoisted(() => ({ repaint: vi.fn(), refresh: vi.fn(async () => {}) }));
vi.mock('../sidebar-shell/interaction-globals', async (orig) => ({
    ...(await orig<typeof import('../sidebar-shell/interaction-globals')>()),
    repaintDrawerRows: () => actions.repaint(), refreshGroups: () => actions.refresh(),
}));


const GROUP = {
    status: 'ok',
    groups: [{
        group_uuid: 'u1', name: 'research', position: 0, members: [], member_session_uuids: [],
        colour: 'teal', gradient: null, animation: 'pulse', style_source: 'stored', icon: null,
    }],
};

afterEach(() => { GroupColor.close(); setDrawerEnv(null); GroupStore.reset(); document.body.innerHTML = ''; });

describe('styleAttrs', () => {
    it('stamps colour, gradient and a non-none animation', () => {
        expect(styleAttrs({ colour: 'teal', gradient: 'tide', animation: 'pulse' }, 'group'))
            .toBe(' data-group-colour="teal" data-group-gradient="tide" data-group-anim="pulse"');
    });
    it('drops a key the palette lacks (a Layout default of indigo paints nothing)', () => {
        expect(styleAttrs({ colour: 'indigo', gradient: null, animation: 'none' }, 'layout')).toBe('');
        expect(styleAttrs(null, 'group')).toBe('');
    });
    it('carries a custom hex inline unless a gradient owns both stops', () => {
        expect(styleAttrs({ colour: '#AABBCC', gradient: null, animation: 'none' }, 'layout'))
            .toBe(' data-layout-colour="custom" style="--row-hue: #aabbcc"');
        expect(styleAttrs({ colour: '#AABBCC', gradient: 'neon', animation: 'none' }, 'group'))
            .toBe(' data-group-colour="custom" data-group-gradient="neon"');
    });
});

describe('fxHtml and nextStyle', () => {
    it('writes 24 windows for a shimmer, escaped, and nothing otherwise', () => {
        const html = fxHtml(' data-group-anim="shimmer"', 'group', 'a<"&');
        expect(html.match(/<i /g)).toHaveLength(24);
        expect(html).toContain('data-t="a&lt;&quot;&amp;"');
        expect(fxHtml(' data-group-anim="pulse"', 'group', 'a')).toBe('');
    });
    it('a flat colour clears the gradient; a gradient keeps the colour', () => {
        const base = { colour: 'teal', gradient: 'tide', animation: 'none' };
        expect(nextStyle(base, 'colour', 'rose')).toEqual({ colour: 'rose', gradient: null, animation: 'none' });
        expect(nextStyle(base, 'gradient', 'neon')).toEqual({ colour: 'teal', gradient: 'neon', animation: 'none' });
    });
});

describe('the popup', () => {
    beforeEach(() => { GroupStore.apply(GROUP); });

    it('opens as a dialog with the group named, and a swatch click writes through the API', async () => {
        const setSessionGroupStyle = vi.fn(async () => ({ ...GROUP, groups: [{ ...GROUP.groups[0], colour: 'rose' }] }));
        setDrawerEnv({ API: { setSessionGroupStyle } });
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        GroupColor.openFull(anchor, 'group', 'u1');
        const dialog = document.getElementById(GroupColor.PICKER_ID) as HTMLElement;
        expect(dialog.getAttribute('role')).toBe('dialog');
        expect(dialog.querySelectorAll('[data-style-field="colour"]')).toHaveLength(9);
        expect(dialog.querySelector('[data-style-value="teal"]')?.getAttribute('aria-checked')).toBe('true');
        (dialog.querySelector('[data-style-value="rose"]') as HTMLElement).click();
        await vi.waitFor(() => expect(setSessionGroupStyle).toHaveBeenCalledWith('u1', { colour: 'rose', gradient: null, animation: 'pulse' }));
    });

    it('a refused write re-reads the groups and reports why', async () => {
        const report = vi.fn();
        actions.refresh.mockClear();
        setDrawerEnv({
            API: { setSessionGroupStyle: async () => { throw new Error('nope'); } }, WriteFailureNotice: { report },
        });
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        GroupColor.openFull(anchor, 'group', 'u1');
        (document.querySelector('[data-style-value="gold"]') as HTMLElement).click();
        await vi.waitFor(() => expect(report).toHaveBeenCalled());
        expect(actions.refresh).toHaveBeenCalled();
        expect(String(report.mock.calls[0]?.[0])).toContain('nope');
    });

    it('an unknown group opens nothing; close removes the dialog', () => {
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        GroupColor.openFull(anchor, 'group', 'missing');
        expect(document.getElementById(GroupColor.PICKER_ID)).toBeNull();
        GroupColor.openFull(anchor, 'group', 'u1');
        GroupColor.close();
        expect(document.getElementById(GroupColor.PICKER_ID)).toBeNull();
    });
});


describe('interaction', () => {
    beforeEach(() => { GroupStore.apply(GROUP); });

    function openPopup(extraEnv: Record<string, unknown> = {}) {
        const answer = { ...GROUP, groups: [{ ...GROUP.groups[0], colour: 'rose' }] };
        setDrawerEnv({
            API: { setSessionGroupStyle: vi.fn(async () => answer) }, ...extraEnv,
        });
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        anchor.focus();
        GroupColor.openFull(anchor, 'group', 'u1');
        return { anchor, dialog: document.getElementById(GroupColor.PICKER_ID) as HTMLElement };
    }

    it('after a pick the checked swatch moves to the picked one (the body is redrawn from the fresh style)', async () => {
        const { dialog } = openPopup();
        expect(dialog.querySelector('[data-style-value="rose"]')?.getAttribute('aria-checked')).toBe('false');
        (dialog.querySelector('[data-style-value="rose"]') as HTMLElement).click();
        await vi.waitFor(() => expect(dialog.querySelector('[data-style-value="rose"]')?.getAttribute('aria-checked')).toBe('true'));
        expect(dialog.querySelector('[data-style-value="teal"]')?.getAttribute('aria-checked')).toBe('false');
    });

    it('Escape closes the popup and hands focus back to the kebab', () => {
        const { anchor } = openPopup();
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(document.getElementById(GroupColor.PICKER_ID)).toBeNull();
        expect(document.activeElement).toBe(anchor);
    });

    it('a mousedown outside closes it without stealing focus; one inside leaves it open', () => {
        const { dialog } = openPopup();
        const other = document.createElement('input');
        document.body.appendChild(other);
        other.focus();
        dialog.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(document.getElementById(GroupColor.PICKER_ID)).not.toBeNull();
        other.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(document.getElementById(GroupColor.PICKER_ID)).toBeNull();
        expect(document.activeElement).toBe(other);
    });

    it('a Layout subject writes through the layouts bridge, not the group API', async () => {
        const setStyle = vi.fn(async () => ({}));
        const layout = { colour: 'teal', gradient: null, animation: 'none', name: 'first' };
        setDrawerEnv({ CloudeWeb: { layouts: { get: () => layout, setStyle } }, API: { setSessionGroupStyle: vi.fn() } });
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        GroupColor.openFull(anchor, 'layout', 'L1');
        (document.querySelector('[data-style-value="neon"]') as HTMLElement).click();
        await vi.waitFor(() => expect(setStyle).toHaveBeenCalledWith('L1', { colour: 'teal', gradient: 'neon', animation: 'none' }));
    });
});
