import { toCplugItem, type CplugItem, type CplugRow } from '../../plugins-page/cplugs-adapter';
import { hasPluginSettings } from '../../plugins-page/plugin-settings-link';
import type { Translate } from '../../sessions/types';

export interface PluginEntry {
    readonly id: string;
    readonly name: string;
    readonly icon: string;
    readonly item: CplugItem;
}

export function pluginEntries(rows: readonly CplugRow[], t: Translate): PluginEntry[] {
    return rows
        .map((row) => toCplugItem(row, t))
        .filter((item) => item.enabled === true && hasPluginSettings(item))
        .map((item): PluginEntry => ({ id: item.cplugId, name: item.name, icon: item.icon ?? 'plug', item }))
        .sort((a, b) => a.name.localeCompare(b.name));
}
