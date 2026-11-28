import type { CplugWidget } from './sdk';

export interface EarlyKind {
  kind: string;
  meta: CplugWidget['meta'];
}

const ENTRIES = import.meta.glob('./*/early.ts', { eager: true }) as Record<string, Record<string, unknown>>;

function isEarlyKind(value: unknown): value is EarlyKind {
  return typeof value === 'object' && value !== null && 'kind' in value && typeof (value as EarlyKind).kind === 'string' && 'meta' in value;
}

export function buildEarlyKinds(entries: Record<string, Record<string, unknown>>): EarlyKind[] {
  return Object.keys(entries)
    .sort()
    .flatMap((path) => {
      const list = entries[path]?.earlyKinds;
      return Array.isArray(list) ? list.filter(isEarlyKind) : [];
    });
}

export const EARLY_KINDS: readonly EarlyKind[] = buildEarlyKinds(ENTRIES);
