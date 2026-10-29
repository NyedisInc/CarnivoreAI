/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { activateRow } from './row-activate';
import { MENU_PAGES } from '../menu-page/menu-pages';

describe('active-session row click with a menu page open', () => {
    const g = globalThis as Record<string, unknown>;
    let closer: ReturnType<typeof vi.fn>;
    let row: HTMLElement;

    beforeEach(() => {
        const page = MENU_PAGES.find((p) => p.id === 'settings')!;
        const host = document.body.appendChild(document.createElement('div'));
        host.id = page.containerId;
        host.appendChild(document.createElement('div'));
        closer = vi.fn(() => host.replaceChildren());
        g.CloudeWeb = { [page.closer]: closer };
        row = document.body.appendChild(document.createElement('div'));
        row.dataset.name = 'cloude_a';
    });
    afterEach(() => {
        document.body.replaceChildren();
        delete g.CloudeWeb;
    });

    it('closes the page and still closes the drawer', async () => {
        const closeAfter = vi.fn();
        await activateRow({ _activeTmuxName: 'cloude_a', _pendingSelection: null, _closeAfterSwitch: closeAfter } as never, row);
        expect(closer).toHaveBeenCalledTimes(1);
        expect(closeAfter).toHaveBeenCalledTimes(1);
    });
});
