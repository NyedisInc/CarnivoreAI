import { readComputers } from '../computers/computers-api';
import { createCatalogData, type CatalogData } from '../catalog/catalog-data.svelte';
import type { CatalogHost } from '../catalog/catalog';
import { cardViews, type CardView } from '../catalog/card';
import { kindCounts, loadInstallCounts, newestItems, type KindCount } from '../catalog/census';
import type { CatalogItem, InstalledItem } from '../catalog/types';
import { FRESH_COUNT } from './query';
import type { Translate } from '../sessions/types';
import { lastCallers, type Caller } from './callers';
import { newSince, prefsReady, readLastCall, stampLastCall } from './elite-prefs';

export type IndexWord = 'online' | 'syncing' | 'dialing' | 'offline';

export interface EliteData {
    readonly catalog: CatalogData;
    readonly handle: string | null;
    /* could not be read */
    readonly computer: string | null;
    readonly listing: readonly CatalogItem[];
    readonly cards: readonly CardView[];
    readonly installed: Record<string, InstalledItem[]>;
    readonly installs: ReadonlyMap<string, number>;
    /* first published */
    readonly fresh: ReadonlySet<string>;
    readonly marked: ReadonlySet<string>;
    readonly lastCall: string | null;
    readonly loading: boolean;
    /* could not be read */
    readonly offline: boolean;
    /* could not be read */
    readonly failure: string | null;
    readonly files: number;
    readonly kinds: readonly KindCount[];
    readonly state: { installed: number; available: number; updates: number };
    readonly installsSum: number | null;
    readonly index: IndexWord;
    callers(handleWord: string): Caller[];
    begin(): void;
    visit(): void;
    refresh(): void;
    redial(): Promise<void>;
}

export function createEliteData(host: CatalogHost, t: Translate): EliteData {
    const catalog = createCatalogData(host, t);
    let handle = $state<string | null>(null);
    let computer = $state<string | null>(null);
    let installs = $state.raw<ReadonlyMap<string, number>>(new Map());
    let redialing = $state(false);
    let lastCall = $state<string | null>(null);
    let lastRead = false;
    let stamped = false;
    let cached = $state.raw<readonly CatalogItem[]>([]);
    $effect.pre(() => {
        if (!catalog.failure && !catalog.loading) cached = catalog.items;
    });

    const listing = $derived<readonly CatalogItem[]>(catalog.failure ? cached : catalog.items);
    const cards = $derived(cardViews([...listing], false));
    const since = $derived(lastCall ? newSince(listing, lastCall) : null);
    const fresh = $derived<ReadonlySet<string>>(since ?? new Set(newestItems(listing, FRESH_COUNT).map((i) => String(i.id))));
    const marked = $derived<ReadonlySet<string>>(since ?? new Set<string>());
    const kinds = $derived(kindCounts(listing));
    const state = $derived.by(() => {
        const rows = listing;
        const held = catalog.installed;
        const installed = rows.filter((i) => (held[String(i.id)]?.length ?? 0) > 0).length;
        const updates = rows.filter((i) => (held[String(i.id)] ?? []).some((r) => r.update_available)).length;
        return { installed, available: rows.length - installed, updates };
    });
    const installsSum = $derived.by(() => {
        if (installs.size === 0) return null;
        let n = 0;
        for (const c of installs.values()) n += c;
        return n;
    });
    const index: IndexWord = $derived(redialing ? 'dialing' : catalog.refreshing ? 'syncing' : catalog.failure ? 'offline' : 'online');

    async function readSide(): Promise<void> {
        try {
            const s = await host.catalogSession();
            handle = s?.signed_in && s.login ? String(s.login) : null;
        } catch {
            handle = null;
        }
        try {
            computer = (await readComputers()).self.label || null;
        } catch {
            computer = null;
        }
    }
    async function readCounts(): Promise<void> {
        if (listing.length === 0) return;
        installs = await loadInstallCounts(host, listing.map((i) => String(i.id)));
    }
    function readPrevious(): void {
        if (lastRead || !prefsReady()) return;
        lastRead = true;
        lastCall = readLastCall();
    }
    async function redial(): Promise<void> {
        redialing = catalog.failure !== null;
        try {
            await catalog.refreshIndex();
            await readCounts();
        } finally {
            redialing = false;
        }
    }

    return {
        catalog,
        get handle() { return handle; },
        get computer() { return computer; },
        get listing() { return listing; },
        get cards() { return cards; },
        get installed() { return catalog.installed; },
        get installs() { return installs; },
        get fresh() { return fresh; },
        get marked() { return marked; },
        get lastCall() { return lastCall; },
        get loading() { return catalog.loading; },
        get offline() { return catalog.failure !== null; },
        get failure() { return catalog.failure; },
        get files() { return listing.length; },
        get kinds() { return kinds; },
        get state() { return state; },
        get installsSum() { return installsSum; },
        get index() { return index; },
        callers: (word) => lastCallers(catalog.ledger, handle ?? word, computer, 5),
        begin: () => {
            lastRead = false;
            stamped = false;
            lastCall = null;
            readPrevious();
            void catalog.refresh().then(readCounts);
            void catalog.openRefresh();
            void readSide();
        },
        visit: () => {
            readPrevious();
            if (stamped || !lastRead) return;
            stamped = true;
            void stampLastCall();
        },
        refresh: () => { void catalog.refresh(); },
        redial,
    };
}
