/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { toggleBandFold, cascadeBandFold, openItemMenu } = vi.hoisted(() => ({ toggleBandFold: vi.fn(), cascadeBandFold: vi.fn(), openItemMenu: vi.fn() }));
vi.mock('./heading-fold', () => ({ toggleBandFold, cascadeBandFold }));
vi.mock('./cascade-hint', () => ({ watchCascadeHint: () => () => {}, CHEVRON_PATH: '' }));
vi.mock('./section-drag', () => ({
    focusHeading: () => {}, onSectionKeydown: () => {}, onSectionPointerDown: () => {}, sectionDragTookClick: () => false,
}));
vi.mock('../item-menu/open.svelte', () => ({ itemMenuState: { open: false }, openItemMenu }));

import { headingEvents } from './heading-events';

let row: HTMLElement;
let detach: (() => void) | void;

beforeEach(() => {
    toggleBandFold.mockClear(); cascadeBandFold.mockClear(); openItemMenu.mockClear();
    document.body.innerHTML = '<div class="session-sidebar-group__headerrow" data-band-kind="reserved">'
        + '<button class="session-sidebar-group__header" data-group-toggle="g:u1"><span class="lbl">name</span></button>'
        + '<button data-group-menu="u1" class="kebab"></button></div>';
    row = document.querySelector('.session-sidebar-group__headerrow')!;
    detach = headingEvents()(row);
});
afterEach(() => { if (typeof detach === 'function') detach(); });

describe('heading row click folds the tree', () => {
    it('the label click folds (unchanged)', () => {
        (row.querySelector('.lbl') as HTMLElement).click();
        expect(toggleBandFold).toHaveBeenCalledWith('g:u1');
    });
    it('a click on the row outside the toggle button folds too', () => {
        row.click();
        expect(toggleBandFold).toHaveBeenCalledTimes(1);
        expect(toggleBandFold).toHaveBeenCalledWith('g:u1');
    });
    it('Shift+click on the row cascades', () => {
        row.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: true }));
        expect(cascadeBandFold).toHaveBeenCalledWith('g:u1');
    });
    it('the kebab opens its menu and does not fold', () => {
        (row.querySelector('.kebab') as HTMLElement).click();
        expect(openItemMenu).toHaveBeenCalledTimes(1);
        expect(toggleBandFold).not.toHaveBeenCalled();
    });
});
