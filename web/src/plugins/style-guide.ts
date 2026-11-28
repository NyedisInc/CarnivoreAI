import type { PluginSpecimen } from './sdk';
const ENTRIES = import.meta.glob('./*/style-guide/specimens.ts', { eager: true }) as Record<string, Record<string, unknown>>;

function folderId(path: string): string {
  return /^\.\/([^/]+)\//.exec(path)?.[1] ?? '';
}

function isSpecimen(value: unknown): value is PluginSpecimen {
  return typeof value === 'object' && value !== null && 'id' in value && typeof (value as PluginSpecimen).id === 'string' && 'component' in value;
}

export function buildPluginSpecimens(entries: Record<string, Record<string, unknown>>): PluginSpecimen[] {
  return Object.keys(entries)
    .sort((a, b) => folderId(a).localeCompare(folderId(b)))
    .flatMap((path) =>
      Object.values(entries[path] ?? {}).flatMap((exported) => (Array.isArray(exported) ? exported.filter(isSpecimen) : [])),
    );
}

export const PLUGIN_SPECIMENS: readonly PluginSpecimen[] = buildPluginSpecimens(ENTRIES);
