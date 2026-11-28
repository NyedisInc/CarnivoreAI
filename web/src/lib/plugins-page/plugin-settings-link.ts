import type { CplugItem } from './cplugs-adapter';
import { canonicalPluginId } from '../../plugins/host/renamed-ids';

export const PLUGINS_FRAGMENT = '#plugins';

export const SETTINGS_SEGMENT = 'settings';

const LEGACY_TASK_MANAGER_FRAGMENTS: ReadonlySet<string> = new Set(['swarm-settings', 'interactive-todo']);

const DEEP_LINK = /^plugins\/([a-z0-9_.-]+)(?:\/(settings))?$/;

export interface PluginLink {
    readonly cplugId: string;
    readonly settings: boolean;
}

export function pluginSettingsHash(cplugId: string): string {
    return `${PLUGINS_FRAGMENT}/${cplugId}/${SETTINGS_SEGMENT}`;
}

export function pluginLinkOf(hash: string | null | undefined): PluginLink | null {
    if (typeof hash !== 'string') return null;
    const bare = hash.trim().replace(/^#/, '');
    if (LEGACY_TASK_MANAGER_FRAGMENTS.has(bare)) return { cplugId: 'taskmanager', settings: true };
    const match = DEEP_LINK.exec(bare);
    return match ? { cplugId: canonicalPluginId(match[1]!), settings: match[2] === SETTINGS_SEGMENT } : null;
}

export function hasPluginSettings(plugin: Pick<CplugItem, 'settingsSchema' | 'surfaces' | 'state'>): boolean {
    return (plugin.settingsSchema !== null || Boolean(plugin.surfaces?.plugins?.includes('settings-panel'))) && plugin.state !== 'removed';
}
