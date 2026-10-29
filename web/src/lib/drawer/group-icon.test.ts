/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import * as GroupStore from './group-store';
import * as GroupIcon from './group-icon';

/** The drawer's repaint and groups re-read, observed (the popup imports them from the shell's interaction globals directly). */
const actions = vi.hoisted(() => ({ repaint: vi.fn(), refresh: vi.fn(async () => {}) }));
vi.mock('../sidebar-shell/interaction-globals', async (orig) => ({
    ...(await orig<typeof import('../sidebar-shell/interaction-globals')>()),
    repaintDrawerRows: () => actions.repaint(), refreshGroups: () => actions.refresh(),
}));


const body = (icon: unknown, colour = 'teal') => ({
    status: 'ok',
    groups: [{
        group_uuid: 'u1', name: 'research', position: 0, members: [], member_session_uuids: [],
        colour, gradient: null, animation: 'none', style_source: 'stored', icon,
    }],
});

afterEach(() => { GroupIcon.close(); setDrawerEnv(null); GroupStore.reset(); document.body.innerHTML = ''; });

describe('the heading mark', () => {
    beforeEach(() => { GroupStore.apply(body('flask')); });
    it('draws the glyph in the shared box, and nothing for a reserved band or an unknown glyph', () => {
        setDrawerEnv({ CloudeGlyphs: { iconSvg: (id: string) => (id === 'flask' ? '<svg></svg>' : '') } });
        expect(GroupIcon.headingMark('u1')).toBe('<span class="session-sidebar-group__icon" data-group-icon="flask" aria-hidden="true"><svg></svg></span>');
        expect(GroupIcon.headingMark(null)).toBe('');
        expect(GroupIcon.markHtml('from-the-future')).toBe('');
    });
    it('draws nothing before the glyph bridge exists', () => {
        setDrawerEnv({});
        expect(GroupIcon.headingMark('u1')).toBe('');
    });
});

describe('save and popup', () => {
    it('a landed write applies the answer and repaints', async () => {
        GroupStore.apply(body(null));
        actions.repaint.mockClear();
        setDrawerEnv({ API: { setSessionGroupIcon: async () => body('flask') } });
        expect(await GroupIcon.setIcon('u1', 'flask')).toBe(true);
        expect(GroupIcon.iconOf('u1')).toBe('flask');
        expect(actions.repaint).toHaveBeenCalled();
    });
    it('a refused write re-reads the groups and reports why', async () => {
        GroupStore.apply(body(null));
        const report = vi.fn();
        actions.refresh.mockClear();
        setDrawerEnv({
            API: { setSessionGroupIcon: async () => { throw new Error('nope'); } }, WriteFailureNotice: { report },
        });
        expect(await GroupIcon.setIcon('u1', 'flask')).toBe(false);
        expect(actions.refresh).toHaveBeenCalled();
        expect(String(report.mock.calls[0]?.[0])).toContain('nope');
    });
    it('the popup is a dialog wearing the group hue, and closes clean', () => {
        GroupStore.apply(body(null, 'rose'));
        setDrawerEnv({});
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        GroupIcon.open(anchor, 'u1');
        const dialog = document.querySelector('.group-icon-picker') as HTMLElement;
        expect(dialog.getAttribute('role')).toBe('dialog');
        expect((document.getElementById(GroupIcon.MOUNT_ID) as HTMLElement).style.getPropertyValue('--icon-hue')).toBe('var(--drawer-hue-rose)');
        GroupIcon.close();
        expect(document.querySelector('.group-icon-picker')).toBeNull();
        GroupIcon.open(anchor, 'missing');
        expect(document.querySelector('.group-icon-picker')).toBeNull();
    });
});


describe('closing', () => {
    function openPopup() {
        GroupStore.apply(body(null));
        setDrawerEnv({});
        const anchor = document.createElement('button');
        document.body.appendChild(anchor);
        anchor.focus();
        GroupIcon.open(anchor, 'u1');
        return anchor;
    }

    it('Escape closes the popup and hands focus back to the kebab', () => {
        const anchor = openPopup();
        expect(document.querySelector('.group-icon-picker')).not.toBeNull();
        const inside = document.querySelector('.group-icon-picker input, .group-icon-picker button') as HTMLElement;
        inside.focus();
        expect(document.activeElement).toBe(inside);
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        expect(document.querySelector('.group-icon-picker')).toBeNull();
        expect(document.activeElement).toBe(anchor);
    });

    it('a mousedown outside closes it without stealing focus; one inside leaves it open', () => {
        openPopup();
        const other = document.createElement('input');
        document.body.appendChild(other);
        other.focus();
        (document.querySelector('.group-icon-picker') as HTMLElement).dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(document.querySelector('.group-icon-picker')).not.toBeNull();
        other.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        expect(document.querySelector('.group-icon-picker')).toBeNull();
        expect(document.activeElement).toBe(other);
    });
});
