/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { layerShowing, modalShowing } from './escape-guards';

function addFileDrawer(): void {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay config-editor-picker-overlay';
    const content = document.createElement('div');
    content.className = 'config-editor-picker-content';
    content.setAttribute('role', 'dialog');
    content.setAttribute('aria-modal', 'true');
    overlay.append(content);
    document.body.append(overlay);
}

beforeEach(() => {
    document.body.className = '';
    document.body.replaceChildren();
});

afterEach(() => {
    document.body.className = '';
    document.body.replaceChildren();
});

test('a docked file drawer owns no Escape: the page beside it still closes', () => {
    addFileDrawer();
    document.body.classList.add('right-drawer-docked');
    expect(modalShowing(document)).toBe(false);
    expect(layerShowing(document)).toBe(false);
});

test('an undocked file overlay (a phone) is a real layer and keeps Escape', () => {
    addFileDrawer();
    expect(modalShowing(document)).toBe(true);
    expect(layerShowing(document)).toBe(true);
});

test('a real dialog beside a docked drawer still owns Escape', () => {
    addFileDrawer();
    document.body.classList.add('right-drawer-docked');
    const dialog = document.createElement('div');
    dialog.className = 'modal-overlay';
    document.body.append(dialog);
    expect(modalShowing(document)).toBe(true);
});
