
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

export interface SliceFailure {
  pluginId: string;
  reason: string;
}

export function registerSlices(
  slices: Array<[string, PluginSlice]>,
  also?: (pluginId: string, slice: PluginSlice) => unknown,
): SliceFailure[] {
  const failures: SliceFailure[] = [];
  for (const [pluginId, slice] of slices) {
    try {
      registerFragment(pluginId, slice);
      also?.(pluginId, slice);
    } catch (error) {
      const reason = error instanceof Error ? error.message : String(error);
      failures.push({ pluginId, reason });
      console.error('i18n: plugin catalog slice refused, its strings render as keys', { pluginId, reason });
    }
  }
  return failures;
}

export function registerPluginSlices(also?: (pluginId: string, slice: PluginSlice) => unknown): SliceFailure[] {
  return registerSlices(pluginSlices(), also);
}
