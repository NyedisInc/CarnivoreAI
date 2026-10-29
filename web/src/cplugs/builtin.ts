import type { CplugWeb } from './sdk';

export const ORDER_HINT: readonly string[] = ['huddle', 'unread', 'share', 'save', 'flow', 'reviewboard', 'tmdevtools', 'crate', 'devwidgetlab'];

const ENTRIES = import.meta.glob('./*/index.ts', { eager: true }) as Record<string, Record<string, unknown>>;
const PLATFORM_FOLDERS: ReadonlySet<string> = new Set(['sdk', 'host']);

function folderId(path: string): string {
  return /^\.\/([^/]+)\//.exec(path)?.[1] ?? '';
}

export function buildShipList(entries: Record<string, Record<string, unknown>>): CplugWeb[] {
  const rank = new Map(ORDER_HINT.map((id, i) => [id, i] as const));
  const ids = Object.keys(entries).map(folderId).filter((id) => id && !PLATFORM_FOLDERS.has(id))
    .sort((a, b) => (rank.get(a) ?? rank.size) - (rank.get(b) ?? rank.size) || a.localeCompare(b));
  return ids.map((id) => {
    const found = entries[`./${id}/index.ts`]?.[`${id}Cplug`] as CplugWeb | undefined;
    if (!found) throw new Error(`plugin folder ${id} has an index.ts that does not export ${id}Cplug`);
    return found;
  });
}

export const BUILTIN_CPLUGS: readonly CplugWeb[] = buildShipList(ENTRIES);
