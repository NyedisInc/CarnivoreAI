import { afterRender as renameAfterRender } from './rename';
import { sidebarShell } from '../sidebar-shell/shell.svelte';
import { afterRender } from '../sidebar-shell/row-focus';
import { arrange, type ArrangedRow } from './arrangement';
import * as bar from './bar';
import { currentMode } from './density';
import { publishFloorRows } from './floor-feed.svelte';
import * as G from './group-store';
import type { ListingVerdict } from './listing-state';
import { FILTER_ONLY_QUERY, effectiveQuery } from './search';
import * as S from './store';

export interface PaintTarget {
    listEl: HTMLElement | null;
    _rows: ArrangedRow[];
    _listing: ListingVerdict;
    _missing: string[];
    _dragging: boolean;
}

export function repaint(ctrl: PaintTarget): boolean {
    const listEl = ctrl.listEl;
    if (!listEl) return false;
    const density = currentMode();
    const arranged = arrange(ctrl._rows);
    const rows = arranged.rows;
    publishFloorRows(rows);
    const missing = arranged.missing;
    ctrl._missing = missing;
    const state = S.current();
    const query = effectiveQuery();
    const opts = {
        collapsed: S.viewCollapsed(),
        dragging: !!ctrl._dragging,
        query,
        searchList: query !== '' && query !== FILTER_ONLY_QUERY && !ctrl._dragging,
    };
    bar.paint();
    listEl.setAttribute('data-listing-ok', ctrl._listing.ok ? '1' : '0');
    listEl.setAttribute('data-order-missing', String(missing.length));
    listEl.setAttribute('data-arrangement-state', state.status);
    listEl.setAttribute('data-density', density);
    listEl.setAttribute('data-groups-state', G.current().status);
    listEl.setAttribute('data-search-active', query ? '1' : '0');
    const drawn = sidebarShell.paint(listEl, {
        rows, density, listing: ctrl._listing, missing, arrangement: { ...state, collapsed: opts.collapsed }, opts,
    });
    if (!drawn) {
        console.error('SessionSidebar: the drawer list could not be drawn (a module it needs is missing)');
        return false;
    }
    afterRender();
    renameAfterRender();
    sidebarShell.paintSelection(ctrl as unknown as Parameters<typeof sidebarShell.paintSelection>[0]);
    return true;
}
