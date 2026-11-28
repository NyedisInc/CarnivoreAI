import { registerPluginBinding, unregisterPluginBinding } from '../../opscenter/cells/registry';
import { pluginKindMeta, registerPluginKind, setPanelProvider, unregisterPluginKind } from '../../opscenter/engine/plugin-kinds';
import type { PluginKind } from '../../opscenter/engine/types';
import { setPluginPreview } from '../../opscenter/layout-editor/thumbnails';
import { setPluginIconUrl } from '../../opscenter/ui/plugin-icon-registry.svelte';
import { registerPluginDeclaration, unregisterPluginDeclaration } from '../../opscenter/widgets/fit-declarations';
import { registerPluginManifest, unregisterPluginManifest } from '../../opscenter/widgets/core-manifests';
import { GRID_SIZE_NAMES, NAMED_SIZE_UNITS, isGridSizeName, type GridSizeName } from '../../opscenter/widgets/named-sizes';
import type { FitSize, WidgetManifest } from '../../opscenter/widgets/types';
import { i18n, t } from '../i18n/index.svelte';
import { toCplugItem, type CplugItem, type CplugRow, type CplugViewRow } from '../plugins-page/cplugs-adapter';
import type { DeclarativeWidgetDecl } from '../plugins/store.svelte';
import PluginViewCell from '../../opscenter/cells/plugin-view/Cell.svelte';
import DeclarativeWidgetCell from './DeclarativeWidgetCell.svelte';
import { DEFAULT_PANEL_MIN, INSTALL_KEY_CHARS, MAX_MIN_UNITS, PANEL_FIT, PANEL_TAIL } from '../../opscenter/cells/plugin-view/constants';
import { panelMeta } from '../../opscenter/cells/plugin-view/definition';

export { PANEL_FIT };

const TOO_SHORT_SIZES: readonly GridSizeName[] = ['small', 'wide'];

const DEFAULT_FITS: PanelFits = { sizes: ['medium', 'large', 'full'], min: DEFAULT_PANEL_MIN, anySize: true };

export interface PanelFits {
    readonly sizes: readonly GridSizeName[];
    readonly min: FitSize;
    readonly anySize: boolean;
}
const STRING_OWNER = 'panelviews';
const KIND_SHAPE = /^(?=.{3,64}$)[a-z][a-z0-9-]*\.[a-z][a-z0-9-]*$/;

export type PanelRow = CplugRow & {
    readonly declarative_widget?: DeclarativeWidgetDecl | null;
};

export interface PanelEntry {
    readonly kind: string;
    readonly key: string;
    readonly plugin: CplugItem;
    readonly view: string;
    readonly title: string;
    readonly tail: string;
    readonly fits: PanelFits;
    readonly declarative?: boolean;
    readonly popout?: boolean;
}

export function isPopoutEnabled(value: unknown): boolean | undefined {
    if (typeof value === 'boolean') return value;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
        const enabled = (value as { enabled?: unknown }).enabled;
        if (typeof enabled === 'boolean') return enabled;
        return true;
    }
    return undefined;
}

export const panels = $state<{ list: PanelEntry[]; loaded: boolean }>({ list: [], loaded: false });
const MANIFESTS = new Map<string, WidgetManifest>();
const PANEL_KINDS = new Set<string>();

export function word(raw: string): string {
    return raw.toLowerCase().replace(/[^a-z0-9-]+/g, '-').replace(/^-+|-+$/g, '') || 'x';
}

export function fitsOf(raw: CplugViewRow['fits']): PanelFits {
    if (!raw || !Array.isArray(raw.sizes) || raw.sizes.length === 0 || !raw.sizes.every(isGridSizeName)) return DEFAULT_FITS;
    const sizes = GRID_SIZE_NAMES.filter((name) => raw.sizes?.includes(name) && !TOO_SHORT_SIZES.includes(name));
    if (sizes.length === 0) return DEFAULT_FITS;
    const lowest = { w: Math.min(...sizes.map((n) => NAMED_SIZE_UNITS[n].w)), h: Math.min(...sizes.map((n) => NAMED_SIZE_UNITS[n].h)) };
    const whole = (v: unknown, cap: number): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= Math.min(MAX_MIN_UNITS, cap) ? v : null);
    const min = { w: whole(raw.min?.w, lowest.w) ?? lowest.w, h: whole(raw.min?.h, lowest.h) ?? lowest.h };
    return { sizes, min, anySize: raw.anySize === true };
}

export function landingFit(fits: PanelFits): FitSize {
    const name = fits.sizes.includes('large') ? 'large' : fits.sizes[0];
    const units = NAMED_SIZE_UNITS[name ?? 'large'];
    return { w: units.w, h: units.h };
}

export function panelEntries(rows: readonly PanelRow[]): PanelEntry[] {
    const out: PanelEntry[] = [];
    const seen = new Set<string>();
    for (const row of rows) {
        const isSidecar = row.runtime === 'sidecar';
        const hasCompiledViews = row.runtime === 'compiled' && (row.views?.length ?? 0) > 0;
        if ((!isSidecar && !hasCompiledViews) || !row.enabled || row.state !== 'active') continue;
        const plugin = toCplugItem(row, t);
        const tail = row.install_key ? `${PANEL_TAIL}-${word(row.install_key).slice(0, INSTALL_KEY_CHARS)}` : PANEL_TAIL;
        const rowPopout = isPopoutEnabled(row.popout);
        const mine = (row.views ?? []).filter((view) => view.surfaces.includes('panel'));
        for (const view of mine) {
            const kind = `${word(row.id)}.${word(view.name)}`;
            if (!KIND_SHAPE.test(kind) || kind.startsWith('core.')) continue;
            if (seen.has(kind) || (pluginKindMeta(kind) && !PANEL_KINDS.has(kind))) {
                console.warn(`cplug panel view skipped, its widget kind is taken: ${kind}`);
                continue;
            }
            seen.add(kind);
            const title = mine.length > 1 ? `${plugin.name} ${view.name}` : plugin.name;
            const popout = isPopoutEnabled(view.popout) ?? rowPopout ?? false;
            out.push({ kind, key: `${row.id}:${row.install_key ?? ''}:${view.name}`, plugin, view: view.name, title, tail, fits: fitsOf(view.fits), popout });
        }
        const dw = row.declarative_widget;
        if (dw && typeof dw === 'object') {
            const rawName = typeof dw.id === 'string' && dw.id.trim() ? dw.id.trim() : 'widget';
            const localName = rawName.startsWith(`${row.id}.`) ? rawName.slice(row.id.length + 1) : rawName;
            const viewName = word(localName || 'widget');
            const kind = `${word(row.id)}.${viewName}`;
            if (!KIND_SHAPE.test(kind) || kind.startsWith('core.')) continue;
            if (seen.has(kind) || (pluginKindMeta(kind) && !PANEL_KINDS.has(kind))) {
                console.warn(`cplug declarative widget skipped, its widget kind is taken: ${kind}`);
                continue;
            }
            seen.add(kind);
            const dwTitle = typeof dw.title === 'string' && dw.title.trim() ? dw.title.trim() : '';
            const title = dwTitle || plugin.name;
            const rawFits: CplugViewRow['fits'] = dw.fits
                ? {
                    ...(Array.isArray(dw.fits.sizes) ? { sizes: dw.fits.sizes } : {}),
                    ...(dw.fits.min ? { min: dw.fits.min } : {}),
                    ...(typeof dw.fits.anySize === 'boolean' ? { anySize: dw.fits.anySize } : {}),
                }
                : Array.isArray(dw.sizes)
                    ? { sizes: dw.sizes }
                    : undefined;
            const popout = isPopoutEnabled(dw.popout) ?? rowPopout ?? false;
            out.push({
                kind,
                key: `${row.id}:${row.install_key ?? ''}:declarative:${viewName}`,
                plugin,
                view: viewName,
                title,
                tail,
                fits: fitsOf(rawFits),
                declarative: true,
                popout,
            });
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

function register(entry: PanelEntry): void {
    const titleKey = titleKeyOf(entry.kind, entry.title);
    try {
        i18n.extendCatalog?.(STRING_OWNER, { [titleKey]: entry.title });
    } catch {
    }
    const meta = panelMeta(entry.kind, titleKey, entry.fits.min, entry.plugin.icon);
    const kind = entry.kind as PluginKind;
    PANEL_KINDS.add(entry.kind);
    INFO.set(entry.kind, infoKeysOf(entry));
    setPluginPreview(entry.kind, entry.plugin.imagePath);
    setPluginIconUrl(entry.kind, entry.plugin.iconUrl);
    registerPluginKind(kind, meta);
    registerPluginDeclaration({ id: kind, instancing: 'per-target', fits: { sizes: [...entry.fits.sizes], anySize: entry.fits.anySize, max_per_surface: 1 } });
    MANIFESTS.set(kind, registerPluginManifest(kind, meta, { category: 'plugins', type: 'plugin', capabilities: [] }, entry.plugin.version ?? '1.0.0'));
    registerPluginBinding(kind, { component: entry.declarative ? DeclarativeWidgetCell : PluginViewCell });
}

function unregister(kind: string): void {
    PANEL_KINDS.delete(kind);
    INFO.delete(kind);
    MANIFESTS.delete(kind);
    setPluginIconUrl(kind, null);
    unregisterPluginKind(kind);
    unregisterPluginDeclaration(kind);
    unregisterPluginManifest(kind);
    unregisterPluginBinding(kind);
}

export function setPanels(rows: readonly PanelRow[]): void {
    const list = panelEntries(rows);
    const nextKinds = new Set(list.map((entry) => entry.kind));
    for (const prev of [...PANEL_KINDS]) {
        if (!nextKinds.has(prev)) unregister(prev);
    }
    for (const entry of list) register(entry);
    panels.list = list;
    panels.loaded = true;
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
    isPanel: (kind) => panels.list.some((entry) => entry.kind === kind),
    canPopOut: (kind) => panelOf(kind)?.popout === true,
    tail: (kind) => panelOf(kind)?.tail,
    info: (kind) => INFO.get(kind),
    revision: () => panels.list,
    loaded: () => panels.loaded,
    fit: (kind) => { const entry = panelOf(kind); return entry ? landingFit(entry.fits) : PANEL_FIT; },
});
