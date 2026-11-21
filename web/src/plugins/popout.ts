import type { CplugPopout } from './sdk';
import { SHIP_ORDER } from './order';

const ENTRIES = import.meta.glob('./*/popout.ts', { eager: true }) as Record<string, Record<string, unknown>>;
function isPopout(value: unknown): value is CplugPopout {
  return typeof value === 'object' && value !== null && 'id' in value && 'manifest' in value && 'tabs' in value;
}

export function buildPopoutList(entries: Record<string, Record<string, unknown>>): CplugPopout[] {
  const rank = new Map(SHIP_ORDER.map((id, i) => [id, i] as const));
  return Object.values(entries).flatMap((module) => Object.values(module).filter(isPopout))
    .sort((a, b) => (rank.get(a.id) ?? rank.size) - (rank.get(b.id) ?? rank.size) || a.id.localeCompare(b.id));
}

export const POPOUT_CPLUGS: readonly CplugPopout[] = buildPopoutList(ENTRIES);
