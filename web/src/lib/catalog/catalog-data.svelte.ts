/* could not be determined */
import { reasonOf } from '../../../../client/js/labels/skill.js';
import type { Translate } from '../sessions/types';
import { cardViews, type CardView } from './card';
import { palettesFrom, pendingOf } from './theme-palettes';
import type { PreviewPalette } from '../themes-page/preview-palette';
import type { CatalogHost } from './catalog';
import { IDLE, installedState, seededState, transition, type InstallState } from './install-actions';
import { isAppOwnSource } from './app-own';
import { anyUpdate, groupInstalled, sameCopy } from './installed-rows';
import type { CatalogIndexState, CatalogItem, InstalledItem } from './types';

/* and the three */
export interface CatalogData {
    readonly index: CatalogIndexState | null;
    readonly items: readonly CatalogItem[];
    readonly cards: readonly CardView[];
    readonly untrustedCards: readonly CardView[];
    readonly palettes: ReadonlyMap<string, PreviewPalette>;
    readonly installed: Record<string, InstalledItem[]>;
    readonly ledger: readonly InstalledItem[];
    /* could not be read */
    readonly failure: string | null;
    readonly loading: boolean;
    readonly refreshing: boolean;
    readonly isEmpty: boolean;
    stateFor(id: string | null): InstallState;
    send(id: string | null, event: Parameters<typeof transition>[1]): void;
    setInstalled(id: string | null, row: InstalledItem | null, installId?: string | null): void;
    refresh(): Promise<void>;
    refreshIndex(): Promise<void>;
    openRefresh(): Promise<void>;
}

export const NO_PALETTES: ReadonlyMap<string, PreviewPalette> = new Map();

export function createCatalogData(host: CatalogHost, t: Translate): CatalogData {
    let index = $state<CatalogIndexState | null>(null);
    let items = $state<CatalogItem[]>([]);
    let untrusted = $state<CatalogItem[]>([]);
    let ledger = $state<InstalledItem[]>([]);
    let states = $state<Record<string, InstallState>>({});
    let failure = $state<string | null>(null);
    let loading = $state(true);
    let refreshing = $state(false);
    let palettes = $state.raw<ReadonlyMap<string, PreviewPalette>>(NO_PALETTES);
    let followUps = 0;
    let followSerial: number | null = null;

    const installed = $derived(groupInstalled(ledger));
    const cards = $derived(cardViews(items, false));
    const untrustedCards = $derived(cardViews(untrusted, true));
    const isEmpty = $derived(!failure && cards.length === 0 && untrustedCards.length === 0);

    function stateFor(id: string | null): InstallState {
        return (id && states[id]) || IDLE;
    }

    function send(id: string | null, event: Parameters<typeof transition>[1]): void {
        if (!id) return;
        if (event.kind === 'dismiss' && stateFor(id).kind === 'verifying') {
            const held = installed[id];
            states[id] = held && held.length ? installedState(anyUpdate(held)) : IDLE;
            return;
        }
        states[id] = transition(stateFor(id), event);
    }

    function setInstalled(id: string | null, row: InstalledItem | null, installId: string | null = null): void {
        if (!id) return;
        if (row) {
            const next = ledger.filter((entry) => entry && !(entry.item_id === id && sameCopy(entry, row)));
            next.push(row);
            ledger = next;
        } else {
            ledger = ledger.filter(
                (entry) => entry && !(entry.item_id === id && (!installId || entry.install_id === installId)),
            );
        }
    }

    async function loadPalettes(): Promise<void> {
        if (!host.themePalettes) return;
        try {
            const response = await host.themePalettes();
            palettes = palettesFrom(response);
            const serial = index?.serial ?? null;
            if (serial !== followSerial) {
                followSerial = serial;
                followUps = 0;
            }
            if (pendingOf(response).length > 0 && followUps < 3) {
                followUps += 1;
                setTimeout(() => void loadPalettes(), 5000);
            }
        } catch {
        }
    }

    async function refresh(): Promise<void> {
        try {
            const [listing, rows] = await Promise.all([host.listItems(), host.listInstalled()]);
            index = listing.index ?? null;
            items = listing.items ?? [];
            untrusted = listing.untrusted ?? [];
            const all = (rows.items ?? []).filter((row) => !isAppOwnSource(row.source_index_url));
            ledger = all;
            const byItem = groupInstalled(all);
            const next: Record<string, InstallState> = {};
            for (const item of items) {
                const id = item && item.id;
                if (!id) continue;
                const held = byItem[id];
                next[id] = seededState(stateFor(id), held ? anyUpdate(held) : null, !!held);
            }
            states = next;
            failure = null;
        } catch (error) {
            index = null;
            items = [];
            untrusted = [];
            failure = reasonOf(error, t);
        } finally {
            loading = false;
        }
        void loadPalettes();
    }

    async function refreshIndex(): Promise<void> {
        refreshing = true;
        try {
            await host.refreshIndex();
            await refresh();
        } catch (error) {
            failure = reasonOf(error, t);
        } finally {
            refreshing = false;
        }
    }

    async function openRefresh(): Promise<void> {
        if (!host.opened) return;
        try {
            await host.opened();
        } catch {
            return;
        }
        await refresh();
    }

    return {
        get index() { return index; },
        get items() { return items; },
        get cards() { return cards; },
        get untrustedCards() { return untrustedCards; },
        get palettes() { return palettes; },
        get installed() { return installed; },
        get ledger() { return ledger; },
        get failure() { return failure; },
        get loading() { return loading; },
        get refreshing() { return refreshing; },
        get isEmpty() { return isEmpty; },
        stateFor,
        send,
        setInstalled,
        refresh,
        refreshIndex,
        openRefresh,
    };
}
