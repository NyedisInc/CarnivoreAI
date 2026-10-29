import { ensurePanel, unmountPanel } from '../mount';
import SearchPanel from './SearchPanel.svelte';
import { SearchController } from './search-controller.svelte';
import { browserSearchHost, type ControllerLike } from './search-host';
import { inputFocus } from '../../opscenter/lib/input-focus.svelte';
import { SvelteMap } from 'svelte/reactivity';

const cells = new SvelteMap<string, SearchController>();
let serial = 0;

export function focusedCellSearch(): SearchController | null {
    const active = typeof document === 'undefined' ? null : document.activeElement;
    for (const search of cells.values()) {
        if (search.containsTarget(active)) return search;
    }
    return cells.get(inputFocus.owner ?? '') ?? null;
}

export function registerCellSearch(slot: string, client: ControllerLike, container: HTMLElement): () => void {
    const id = container.id || `terminal-cell-search-${++serial}`;
    container.id = id;
    const built = new SearchController(browserSearchHost(client));
    cells.set(slot, built);
    ensurePanel(id, SearchPanel as never, { controller: built } as never);
    return () => {
        if (cells.get(slot) === built) cells.delete(slot);
        built.close();
        built.rail.dispose();
        unmountPanel(id);
    };
}

export function cellSearchFor(slot: string): SearchController | null {
    return cells.get(slot) ?? null;
}

export function openCellSearch(slot: string): boolean {
    const found = cells.get(slot);
    if (!found) return false;
    found.open();
    return true;
}

export function toggleCellSearch(slot: string): boolean {
    const found = cells.get(slot);
    if (!found) return false;
    found.toggle();
    return true;
}

export function cellSearchOpen(slot: string): boolean | null {
    const found = cells.get(slot);
    return found ? found.isOpen() : null;
}
