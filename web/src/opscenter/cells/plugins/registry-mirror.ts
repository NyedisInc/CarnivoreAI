
export interface PluginMirrorRow {
  readonly id: string;
  readonly surfaces: readonly string[];
  readonly contributionCount: number;
  readonly mirror: true;
}

const MANIFESTS = import.meta.glob<{ id: string; surfaces: { plugins?: string[] } }>(
  '../../../../../src/cplugs/*/cplug.json',
  { eager: true, import: 'default' },
);

export const PLUGIN_REGISTRY: readonly PluginMirrorRow[] = Object.values(MANIFESTS)
  .filter((m) => (m.surfaces.plugins ?? []).length > 0)
  .map((m) => ({ id: m.id, surfaces: m.surfaces.plugins ?? [], contributionCount: (m.surfaces.plugins ?? []).length, mirror: true as const }))
  .sort((a, b) => (a.id < b.id ? -1 : 1));
