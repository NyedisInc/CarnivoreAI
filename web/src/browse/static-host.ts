import type { CatalogHost } from '../lib/catalog/catalog';
import type {
    CatalogIndexState,
    CatalogItem,
    CatalogListResponse,
    ThemePalettesResponse,
} from '../lib/catalog/types';

export const INDEX_URL = 'v1/index.json';
export const PALETTES_URL = 'v1/theme-palettes.json';
export const SIGNATURE_URL = 'v1/index.json.minisig';

interface IndexDocument {
    serial?: number | null;
    generated_at?: string | null;
    expires_at?: string | null;
    items?: Array<CatalogItem & { versions?: Array<{ published_at?: string }> }>;
    featured?: string[];
}

async function readKeyId(fetchImpl: typeof fetch): Promise<string | null> {
    try {
        const r = await fetchImpl(SIGNATURE_URL, { cache: 'no-cache' });
        return r.ok ? keyIdOfSignature(await r.text()) : null;
    } catch {
        // the trust line
        return null;
    }
}

const READONLY = 'the public catalog page is read only';

const instant = (stamp: string): number => Date.parse(stamp);

export function firstPublishedAt(versions: ReadonlyArray<{ published_at?: string }> | null | undefined): string | null {
    const stamps = (versions ?? []).map((v) => v.published_at).filter((s): s is string => typeof s === 'string');
    if (!stamps.length) return null;
    if (stamps.some((s) => Number.isNaN(instant(s)))) return stamps.reduce((a, b) => (b < a ? b : a));
    return stamps.reduce((a, b) => (instant(b) < instant(a) ? b : a));
}

export function keyIdOfSignature(text: string): string | null {
    const line = text.split(/\r?\n/)[1]?.trim();
    if (!line) return null;
    try {
        const raw = atob(line);
        if (raw.length < 10) return null;
        return Array.from(raw.slice(2, 10), (c) => c.charCodeAt(0).toString(16).padStart(2, '0')).reverse().join('').toUpperCase();
    } catch {
        return null;
    }
}

export function listFromIndex(doc: IndexDocument, now: number = Date.now(), keyId: string | null = null): CatalogListResponse {
    const featured = doc.featured ?? [];
    const items = (doc.items ?? []).map((item) => {
        const rank = item.id ? featured.indexOf(item.id) : -1;
        return {
            ...item,
            installed: null,
            untrusted: false,
            featured_rank: rank >= 0 ? rank : null,
            first_published_at: firstPublishedAt(item.versions),
        } as CatalogItem;
    });
    const expires = doc.expires_at ? instant(doc.expires_at) : NaN;
    const index: CatalogIndexState = {
        serial: doc.serial ?? null,
        generated_at: doc.generated_at ?? null,
        as_of: doc.generated_at ?? null,
        expires_at: doc.expires_at ?? null,
        degraded: !Number.isNaN(expires) && now > expires,
        stale: false,
        refusal: null,
        key_id: keyId,
    };
    return { index, items, untrusted: [] };
}

const refuse = <T>(): Promise<T> => Promise.reject(new Error(READONLY));

export function staticCatalogHost(fetchImpl: typeof fetch = (...a) => fetch(...a)): CatalogHost {
    let held: Promise<CatalogListResponse> | null = null;
    const load = (): Promise<CatalogListResponse> => {
        held ??= Promise.all([
            fetchImpl(INDEX_URL, { cache: 'no-cache' }).then((r) => {
                if (!r.ok) throw new Error(`index answered ${r.status}`);
                return r.json() as Promise<IndexDocument>;
            }),
            readKeyId(fetchImpl),
        ])
            .then(([doc, keyId]) => listFromIndex(doc, Date.now(), keyId))
            .catch((error) => {
                held = null;
                throw error;
            });
        return held;
    };
    return {
        listItems: load,
        refreshIndex: async () => {
            held = null;
            return (await load()).index ?? {};
        },
        listInstalled: async () => ({ items: [] }),
        themePalettes: async (): Promise<ThemePalettesResponse> => {
            try {
                const r = await fetchImpl(PALETTES_URL);
                if (!r.ok) return { items: {}, pending: [] };
                const body = (await r.json()) as Partial<ThemePalettesResponse>;
                if (!body || typeof body.items !== 'object' || body.items === null) return { items: {}, pending: [] };
                return { items: body.items, pending: Array.isArray(body.pending) ? body.pending : [] };
            } catch {
                return { items: {}, pending: [] };
            }
        },
        previewInstall: refuse,
        install: refuse,
        uninstall: refuse,
        item: async (itemId) => (await load()).items?.find((i) => i.id === itemId) ?? null,
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        tryInScratch: refuse,
        listProjects: async () => [],
        currentProjectPath: async () => null,
        itemRatings: async (itemId) => ({ item_id: itemId, count: 0, average: null, histogram: {}, reviews: [] }),
        rateItem: refuse,
        removeRating: refuse,
        itemInstalls: async (itemId) => ({ item_id: itemId, count: null }),
        installCounts: async () => ({ items: {} }),
        folderPicker: () => null,
        catalogSession: async () => ({ signed_in: false }),
        startDeviceFlow: refuse,
        pollDeviceFlow: refuse,
        startGoogleFlow: refuse,
        pollGoogleFlow: refuse,
        startEmailFlow: refuse,
        verifyEmailCode: refuse,
        verifyGoogleMailboxCode: refuse,
        signOutOfCatalog: async () => ({ signed_in: false }),
    };
}
