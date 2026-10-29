/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it } from 'vitest';
import * as Rename from '../drawer/rename';
import { headingRename, openHeadingRename } from './heading-rename.svelte';
import { beginRowRename } from './row-rename';

function renameableRow(): HTMLElement {
    const row = document.createElement('div');
    row.className = 'session-sidebar-row';
    row.dataset.name = 'cloude_a';
    row.dataset.sessionId = 'ses_a';
    row.setAttribute('data-rename-state', 'renameable');
    const name = document.createElement('span');
    name.setAttribute('data-row-name', '');
    row.appendChild(name);
    document.body.append(row);
    return row;
}

beforeEach(() => {
    document.body.innerHTML = '<div id="session-sidebar-live"></div>';
    Rename.afterRender();
});

afterEach(() => {
    headingRename.spec = null;
    Rename.afterRender();
});

it('a shell row will not open its box while the imperative editor is open', () => {
    const host = renameableRow();
    const label = document.createElement('span');
    host.appendChild(label);
    expect(Rename.openEditor({ hostEl: host, nameEl: label, seed: 'layout', save: async () => ({}) })).toBe(true);
    expect(beginRowRename(renameableRow())).toBe(false);
});

it('a shell heading will not open its box while the imperative editor is open', () => {
    const host = renameableRow();
    const label = document.createElement('span');
    host.appendChild(label);
    expect(Rename.openEditor({ hostEl: host, nameEl: label, seed: 'layout', save: async () => ({}) })).toBe(true);
    expect(openHeadingRename({ key: 'g:u1', seed: 'crew', ariaLabel: 'Rename group crew', save: async () => {} } as never)).toBe(false);
});

it('control: with no editor open the shell row opens its box', () => {
    const row = renameableRow();
    row.appendChild(document.createElement('span'));
    expect(beginRowRename(row)).toBe(true);
});
