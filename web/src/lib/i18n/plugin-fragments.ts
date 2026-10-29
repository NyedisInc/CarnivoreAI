
import { registerFragment } from '../../../../client/js/i18n/catalogs.js';

export type PluginSlice = Record<string, string | Record<string, string>>;

const SLICES = import.meta.glob('../../cplugs/*/catalog.en.js', { eager: true, import: 'default' }) as Record<string, PluginSlice>;
const SERVER_SLICES = import.meta.glob('../../../../src/cplugs/*/notify.catalog.en.js', { eager: true, import: 'default' }) as Record<string, PluginSlice>;

export function pluginSlices(): Array<[string, PluginSlice]> {
  const byId = new Map<string, PluginSlice>();
  for (const [path, slice] of [...Object.entries(SLICES), ...Object.entries(SERVER_SLICES)].sort(([a], [b]) => a.localeCompare(b))) {
    const id = /cplugs\/([^/]+)\//.exec(path)?.[1] ?? '';
    byId.set(id, { ...byId.get(id), ...slice });
  }
  return [...byId.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function registerPluginSlices(also?: (pluginId: string, slice: PluginSlice) => unknown): void {
  for (const [pluginId, slice] of pluginSlices()) {
    registerFragment(pluginId, slice);
    also?.(pluginId, slice);
  }
}
