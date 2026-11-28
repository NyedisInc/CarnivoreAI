
const MANIFESTS = import.meta.glob<{ id: string; renamed_from?: string }>('../../../../src/plugins/*/carnivore.toml', {
  eager: true,
  import: 'default',
});

const RENAMED: ReadonlyMap<string, string> = new Map(
  Object.values(MANIFESTS)
    .filter((m) => typeof m.renamed_from === 'string' && m.renamed_from !== '')
    .map((m) => [m.renamed_from as string, m.id]),
);

export function canonicalPluginId(id: string): string {
  return RENAMED.get(id) ?? id;
}
