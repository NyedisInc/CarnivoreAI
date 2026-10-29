import { authFetch } from '../../opscenter/api/auth.svelte';
import type { TabDef } from '../../opscenter/ui/Tabs.svelte';
import { scaleBytes } from '../../opscenter/viz/health';
import type { Translate } from '../sessions/types';
import { CPLUGS_ROUTE, type CplugItem, type CplugSurfaces } from './cplugs-adapter';
import { visibleSchema } from './plugin-extras';
import { hasPluginSettings } from './plugin-settings-link';

export const PANE_TABS = ['overview', 'settings', 'permissions', 'data'] as const;

export type PaneTab = (typeof PANE_TABS)[number];

export const PANE_TAB_MEMORY = 'plugins-pane';

const ADDED_SURFACES = ['tabs', 'widgets', 'plugins', 'menu_links', 'mcp_tools', 'topics', 'feed'] as const;

export type StateTone = 'on' | 'warn' | 'off';

export interface PaneReason {
    readonly kind: 'held' | 'grant';
    readonly lead: string;
    readonly more: string;
}

export interface SurfaceChip {
    readonly key: string;
    readonly label: string;
    readonly count: number | null;
}

export function isPaneTab(value: string): value is PaneTab {
    return (PANE_TABS as readonly string[]).includes(value);
}

export function stateWord(plugin: CplugItem, t: Translate): string {
    if (plugin.tier === 'core' && plugin.state === 'active') return t('plugins.page.pane.state.core');
    return t(`plugins.page.pane.state.${plugin.state}`);
}

export function stateTone(plugin: Pick<CplugItem, 'state'>): StateTone {
    if (plugin.state === 'active') return 'on';
    return plugin.state === 'needs_approval' || plugin.state === 'unavailable' || plugin.state === 'inert' ? 'warn' : 'off';
}

export function paneReason(plugin: CplugItem, t: Translate): PaneReason | null {
    if (plugin.state === 'unavailable') {
        const more = plugin.heldReason
            ? t('plugins.page.pane.reason.held_said', { reason: plugin.heldReason })
            : t('plugins.page.pane.reason.held_unsaid');
        return { kind: 'held', lead: t('plugins.page.pane.reason.held'), more };
    }
    if (plugin.state === 'needs_approval') {
        const labels = plugin.permissions.filter((p) => plugin.missing.includes(p.name)).map((p) => p.label);
        return { kind: 'grant', lead: t('plugins.page.pane.reason.grant'), more: t('plugins.page.pane.reason.grant_more', { names: labels.join(', ') }) };
    }
    return null;
}

export function surfaceChips(surfaces: CplugSurfaces, t: Translate): SurfaceChip[] {
    const chips: SurfaceChip[] = [];
    for (const key of ADDED_SURFACES) {
        const value = surfaces[key];
        if (value === true) chips.push({ key, label: t(`plugins.page.surface.${key}`), count: null });
        else if (Array.isArray(value) && value.length > 0) chips.push({ key, label: t(`plugins.page.surface.${key}`), count: value.length });
    }
    return chips;
}

export function bytesText(bytes: number, t: Translate): string {
    const { unit, value } = scaleBytes(bytes);
    return t(`plugins.page.data.size.${unit}`, { value });
}

export function settingsCount(plugin: CplugItem): number | null {
    if (!plugin.settingsSchema || !hasPluginSettings(plugin)) return null;
    const count = Object.keys(visibleSchema(plugin.cplugId, plugin.settingsSchema).fields).length;
    return count > 0 ? count : null;
}

export function paneTabs(plugin: CplugItem, t: Translate): TabDef[] {
    const waiting = plugin.state === 'needs_approval';
    return [
        { id: 'overview', label: t('plugins.page.pane.tab.overview') },
        { id: 'settings', label: t('plugins.page.pane.tab.settings'), badge: settingsCount(plugin) },
        {
            id: 'permissions',
            label: t('plugins.page.pane.tab.permissions'),
            badge: waiting || plugin.permissions.length === 0 ? null : plugin.permissions.length,
            dot: waiting,
        },
        { id: 'data', label: t('plugins.page.pane.tab.data'), badge: plugin.storageBytes === null ? null : bytesText(plugin.storageBytes, t) },
    ];
}

export function purgeBlocked(plugin: Pick<CplugItem, 'state' | 'tier' | 'name'>, t: Translate): string | null {
    if (plugin.state === 'disabled' || plugin.state === 'removed') return null;
    if (plugin.tier === 'core') return t('plugins.page.data.blocked_core', { name: plugin.name });
    return t('plugins.page.data.blocked_on', { name: plugin.name });
}

export interface PurgePrice {
    readonly id: string;
    readonly files: number;
    readonly bytes: number;
    readonly confirm_token: string;
    readonly dry_run: boolean;
}

export async function purgeCplug(cplugId: string, confirmToken?: string, fetcher: typeof authFetch = authFetch): Promise<PurgePrice> {
    const body = confirmToken === undefined ? { dry_run: true } : { dry_run: false, confirm_token: confirmToken };
    return fetcher<PurgePrice>(`${CPLUGS_ROUTE}/${encodeURIComponent(cplugId)}/purge`, { method: 'POST', body: JSON.stringify(body) });
}
