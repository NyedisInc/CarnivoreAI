
export interface PluginMirrorRow {
  readonly id: string;
  readonly surfaces: readonly string[];
  readonly contributionCount: number;
  readonly mirror: true;
}

type ManifestDoc = {
  id: string;
  surfaces?: { plugins?: string[] };
  ui?: { plugins?: string[] };
};

const MANIFESTS = import.meta.glob<ManifestDoc>(
  '../../../../../src/plugins/*/carnivore.toml',
  { eager: true, import: 'default' },
);

const pluginsOf = (m: ManifestDoc): readonly string[] => m.surfaces?.plugins ?? m.ui?.plugins ?? [];

export const PLUGIN_REGISTRY: readonly PluginMirrorRow[] = Object.values(MANIFESTS)
  .filter((m) => pluginsOf(m).length > 0)
  .map((m) => ({ id: m.id, surfaces: pluginsOf(m), contributionCount: pluginsOf(m).length, mirror: true as const }))
  .sort((a, b) => (a.id < b.id ? -1 : 1));
