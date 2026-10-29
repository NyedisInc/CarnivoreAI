import { registerPluginBinding } from '../../opscenter/cells/registry';
import { pluginKindMeta, registerPluginKind, setPanelProvider } from '../../opscenter/engine/plugin-kinds';
import type { CellMeta, PluginKind, SlotId } from '../../opscenter/engine/types';
import { setPluginPreview } from '../../opscenter/layout-editor/thumbnails';
import { SIZE_UNIT_PX } from '../../opscenter/widgets/fits';
import { registerPluginDeclaration } from '../../opscenter/widgets/fit-declarations';
import { registerPluginManifest } from '../../opscenter/widgets/core-manifests';
import { GRID_SIZE_NAMES, NAMED_SIZE_UNITS, isGridSizeName, type GridSizeName } from '../../opscenter/widgets/named-sizes';
import type { FitSize, WidgetManifest } from '../../opscenter/widgets/types';
import { i18n, t } from '../i18n/index.svelte';
import { toCplugItem, type CplugItem, type CplugRow, type CplugViewRow } from '../plugins-page/cplugs-adapter';
import PanelCell from './PanelCell.svelte';

const PANEL_TAIL = 'panel';
export const PANEL_FIT = { w: 6, h: 5 };
const DEFAULT_FITS: PanelFits = { sizes: ['medium', 'large', 'full'], min: { w: 3, h: 3 }, anySize: true };
const MAX_MIN = 12;

export interface PanelFits {
    readonly sizes: readonly GridSizeName[];
    readonly min: FitSize;
    readonly anySize: boolean;
}
const STRING_OWNER = 'panelviews';
const KIND_SHAPE = /^[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$/;

export interface PanelEntry {
    readonly kind: string;
    readonly key: string;
    readonly plugin: CplugItem;
    readonly view: string;
    readonly title: string;
    readonly tail: string;
    readonly fits: PanelFits;
}

export const panels = $state<{ list: PanelEntry[] }>({ list: [] });
const MANIFESTS = new Map<string, WidgetManifest>();
const PANEL_KINDS = new Set<string>();

export function word(raw: string): string {
    return raw.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '') || 'x';
}

export function fitsOf(raw: CplugViewRow['fits']): PanelFits {
    if (!raw || !Array.isArray(raw.sizes) || raw.sizes.length === 0 || !raw.sizes.every(isGridSizeName)) return DEFAULT_FITS;
    const sizes = GRID_SIZE_NAMES.filter((name) => raw.sizes?.includes(name));
    const lowest = { w: Math.min(...sizes.map((n) => NAMED_SIZE_UNITS[n].w)), h: Math.min(...sizes.map((n) => NAMED_SIZE_UNITS[n].h)) };
    const whole = (v: unknown, cap: number): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= Math.min(MAX_MIN, cap) ? v : null);
    const min = { w: whole(raw.min?.w, lowest.w) ?? lowest.w, h: whole(raw.min?.h, lowest.h) ?? lowest.h };
    return { sizes, min, anySize: raw.anySize === true };
}

export function landingFit(fits: PanelFits): FitSize {
    const name = fits.sizes.includes('large') ? 'large' : fits.sizes[0];
    const units = NAMED_SIZE_UNITS[name ?? 'large'];
    return { w: units.w, h: units.h };
}

export function panelEntries(rows: readonly CplugRow[]): PanelEntry[] {
    const out: PanelEntry[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
        if (row.runtime !== 'sidecar' || !row.enabled || row.state !== 'active') continue;
        const mine = (row.views ?? []).filter((view) => view.surfaces.includes('panel'));
        for (const view of mine) {
            const kind = `${word(row.id)}.${word(view.name)}`;
            if (!KIND_SHAPE.test(kind) || kind.startsWith('core.')) continue;
            if (seen.has(kind) || (pluginKindMeta(kind) && !PANEL_KINDS.has(kind))) {
                console.warn(`cplug panel view skipped, its widget kind is taken: ${kind}`);
                continue;
            }
            seen.add(kind);
            const plugin = toCplugItem(row, t);
            const title = mine.length > 1 ? `${plugin.name} ${view.name}` : plugin.name;
            const tail = row.install_key ? `${PANEL_TAIL}-${word(row.install_key).slice(0, 8)}` : PANEL_TAIL;
            out.push({ kind, key: `${row.id}:${row.install_key ?? ''}:${view.name}`, plugin, view: view.name, title, tail, fits: fitsOf(view.fits) });
        }
    }
    return out;
}

export function titleKeyOf(kind: string, title: string): string {
    let hash = 5381;
    for (const ch of title) hash = ((hash * 33) ^ ch.charCodeAt(0)) >>> 0;
    return `cplug.${STRING_OWNER}.${kind.replace('.', '-')}.${hash.toString(36)}`;
}

const INFO = new Map<string, { about: string; data: string }>();

function infoKeysOf(entry: PanelEntry): { about: string; data: string } {
    const fallback = { about: 'widgets.info.about.plugin_view', data: 'widgets.info.data.plugin_view' };
    const text = entry.plugin.brief?.trim();
    if (!text) return fallback;
    const about = titleKeyOf(entry.kind, `about:${text}`);
    try {
        i18n.extendCatalog?.(STRING_OWNER, { [about]: text });
    } catch {
        return fallback;
    }
    return { about, data: fallback.data };
}

function metaOf(kind: string, titleKey: string, fits: PanelFits): CellMeta {
    return {
        id: `${kind}:${PANEL_TAIL}` as SlotId,
        titleKey,
        icon: 'plug',
        iconTone: 'oc-cyan',
        showCount: false,
        chrome: 'card',
        titleHeight: 31,
        defaultRow: 'r1',
        defaultIndex: 0,
        defaultFr: 1,
        defaultHeight: 320,
        minPx: fits.min.w * SIZE_UNIT_PX.w,
        minHeight: fits.min.h * SIZE_UNIT_PX.h,
        widthStates: [{ name: 'narrow', min: 0 }, { name: 'wide', min: 560 }],
        heightStates: [{ name: 'strip', min: 0 }, { name: 'pane', min: 200 }],
        phoneOrder: 23,
    } as CellMeta;
}

function register(entry: PanelEntry): void {
    const titleKey = titleKeyOf(entry.kind, entry.title);
    try {
        i18n.extendCatalog?.(STRING_OWNER, { [titleKey]: entry.title });
    } catch {
    }
    const meta = metaOf(entry.kind, titleKey, entry.fits);
    const kind = entry.kind as PluginKind;
    PANEL_KINDS.add(entry.kind);
    INFO.set(entry.kind, infoKeysOf(entry));
    setPluginPreview(entry.kind, entry.plugin.imagePath);
    registerPluginKind(kind, meta);
    registerPluginDeclaration({ id: kind, instancing: 'per-target', fits: { sizes: [...entry.fits.sizes], anySize: entry.fits.anySize, max_per_surface: 1 } });
    MANIFESTS.set(kind, registerPluginManifest(kind, meta, { category: 'plugins', type: 'plugin', capabilities: [] }, entry.plugin.version ?? '1.0.0'));
    registerPluginBinding(kind, { component: PanelCell });
}

export function setPanels(rows: readonly CplugRow[]): void {
    const list = panelEntries(rows);
    for (const entry of list) register(entry);
    panels.list = list;
}

export function livePanelManifests(): Readonly<Record<string, WidgetManifest>> {
    const out: Record<string, WidgetManifest> = {};
    for (const entry of panels.list) {
        const manifest = MANIFESTS.get(entry.kind);
        if (manifest) out[manifest.id] = manifest;
    }
    return out;
}

export function panelOf(kind: string): PanelEntry | undefined {
    return panels.list.find((entry) => entry.kind === kind);
}

setPanelProvider({
    manifests: livePanelManifests,
    isPanel: (kind) => PANEL_KINDS.has(kind),
    tail: (kind) => panelOf(kind)?.tail,
    info: (kind) => INFO.get(kind),
    revision: () => panels.list,
    fit: (kind) => { const entry = panelOf(kind); return entry ? landingFit(entry.fits) : PANEL_FIT; },
});
