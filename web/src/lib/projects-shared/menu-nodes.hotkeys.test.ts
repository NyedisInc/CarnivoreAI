/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

import { menuNodes } from './menu-nodes';
import { closeItemMenu } from '../item-menu/open.svelte';
import { openPageRowMenu } from '../item-menu/page-row';
import { projectActions } from './ledger-model';
import { setLocale, t } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { assignMenuKeys, pressMenuKey } from '../menu-keys/menu-keys';

installPopoverPolyfill();
setLocale('en');

afterEach(() => {
    closeItemMenu();
    document.body.replaceChildren();
});

function press(key: string): void {
    const target = (document.activeElement as HTMLElement | null) ?? document.body;
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
    flushSync();
}

function openMenu(onPick: (id: string) => void): HTMLElement {
    const row = document.createElement('div');
    row.tabIndex = 0;
    document.body.append(row);
    const project = { archived_at: null, root: '/a', company_id: null, has_image: true };
    const items = projectActions(project, [{ id: 7, name: 'acme' } as never], true, true);
    const menu = { type: 'pagerow', ctx: { label: 'project menu', nodes: menuNodes(items, t, onPick) } } as const;
    openPageRowMenu(menu, row, { x: 10, y: 10 });
    flushSync();
    return row;
}

test('the project heading menu draws the registry letters, one per item', () => {
    openMenu(() => {});
    const keys = Object.fromEntries(
        [...document.querySelectorAll<HTMLElement>('[data-level="0"] [data-node]')].map((el) => [el.dataset.node, el.dataset.menuKey]),
    );
    expect(keys).toEqual({
        'new-session': 'n',
        'migrate-project': 'm',
        'rename-project': 'r',
        'pick-color': 'c',
        'copy-path': 'y',
        'load-blueprint': 'b',
        'turn-on-agent': 'a',
        'set-image': 'i',
        'remove-image': 'x',
        'regenerate-art': 'g',
        'add-to-company': 'o',
        'archive-project': 'v',
        'delete-project': 'd',
    });
    const drawn = document.querySelector('[data-node="rename-project"] .menu-key');
    expect(drawn?.textContent).toBe('r');
});

test('a key picks its item only while the menu is open and focused', () => {
    const onPick = vi.fn();
    const row = openMenu(onPick);
    expect(document.activeElement?.closest('[role="menu"]'), 'focus is in the menu').not.toBeNull();

    press('d');
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick).toHaveBeenLastCalledWith('delete-project');
    expect(document.querySelector('[role="menu"]'), 'a picked leaf closes the menu').toBeNull();

    row.focus();
    press('d');
    press('r');
    document.body.focus();
    press('r');
    expect(onPick).toHaveBeenCalledTimes(1);

    openMenu(onPick);
    press('o');
    expect(document.querySelector('[data-level="1"]'), 'company submenu open').not.toBeNull();
    expect(onPick).toHaveBeenCalledTimes(1);
    press('a');
    expect(onPick).toHaveBeenLastCalledWith('set-company:7');
});

test('a key typed into a text field inside a menu stays text', () => {
    const run = vi.fn();
    const panel = document.createElement('div');
    panel.setAttribute('role', 'menu');
    panel.innerHTML = '<input /><button data-menu-key="r">rename</button>';
    panel.querySelector('button')!.addEventListener('click', run);
    document.body.append(panel);
    const input = panel.querySelector('input')!;
    const event = new KeyboardEvent('keydown', { key: 'r', bubbles: true, cancelable: true });
    input.dispatchEvent(event);
    expect(pressMenuKey(event, panel)).toBe(false);
    expect(run).not.toHaveBeenCalled();
    expect(assignMenuKeys([{ id: 'rename-a', label: 'rename' }, { id: 'rename-b', label: 'rename again' }])).toEqual(['r', 'e']);
});
