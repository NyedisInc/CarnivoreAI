/* and the three */
import { ensurePanel, unmountPanel } from '../mount';
import { hostDocument, hostWindow } from '../sessions/env';
import SearchPanel from './SearchPanel.svelte';
import { SearchController } from './search-controller.svelte';
import { browserSearchHost, type SearchHost } from './search-host';
import { installKeyRouting } from './search-keys';
import { focusedCellSearch } from './cell-search';

export const SEARCH_CONTAINER_ID = 'terminal-container';

const HEADER_BUTTON_ID = 'terminalSearchBtn';

let controller: SearchController | null = null;

export function terminalSearchController(): SearchController | null {
    return controller;
}

let teardown: Array<() => void> = [];

export function mountTerminalSearch(host?: SearchHost): SearchController | null {
    if (controller) return controller;
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return null;
    const target = doc.getElementById(SEARCH_CONTAINER_ID);
    if (!target || typeof target.appendChild !== 'function') return null;

    const built = new SearchController(host ?? browserSearchHost());
    controller = built;
    ensurePanel(SEARCH_CONTAINER_ID, SearchPanel as never, { controller: built } as never);
    teardown.push(installKeyRouting(() => focusedCellSearch() ?? built, doc));

    const win = hostWindow();
    if (win && typeof win.addEventListener === 'function') {
        const onDestroyed = (): void => built.close();
        win.addEventListener('session-destroyed', onDestroyed);
        teardown.push(() => win.removeEventListener('session-destroyed', onDestroyed));
    }

    wireHeaderButton(doc, built);
    return built;
}

function wireHeaderButton(doc: Document, ctl: SearchController): void {
    const btn = doc.getElementById(HEADER_BUTTON_ID);
    if (!btn || btn.getAttribute('data-search-wired') === '1') return;
    btn.setAttribute('data-search-wired', '1');
    const onClick = (): void => ctl.toggle();
    btn.addEventListener('click', onClick);
    teardown.push(() => {
        btn.removeEventListener('click', onClick);
        btn.removeAttribute('data-search-wired');
    });
}

export function openTerminalSearch(): void {
    (controller ?? mountTerminalSearch())?.open();
}

export function openTerminalSearchAt(query: string, fromEnd: number): boolean {
    const ctl = controller ?? mountTerminalSearch();
    if (!ctl) return false;
    ctl.openAt(query, fromEnd);
    return ctl.isOpen();
}

export function toggleTerminalSearch(): void {
    (controller ?? mountTerminalSearch())?.toggle();
}

export function terminalSearchIsOpen(): boolean {
    return controller?.isOpen() ?? false;
}

export function unmountTerminalSearch(): void {
    controller?.close();
    controller?.rail.dispose();
    for (const undo of teardown) undo();
    teardown = [];
    unmountPanel(SEARCH_CONTAINER_ID);
    controller = null;
}
