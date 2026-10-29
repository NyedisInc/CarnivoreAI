
export const RAIL_SPLIT = '~rail-split';

export interface RailZoneIds {
  top: string[];
  bottom: string[];
}

export function resolveRailZones<T extends { id: string }>(top: readonly T[], bottom: readonly T[], stored: readonly string[]): RailZoneIds {
  const at = stored.indexOf(RAIL_SPLIT);
  if (at === -1) return { top: top.map((i) => i.id), bottom: bottom.map((i) => i.id) };
  const known = new Set([...top, ...bottom].map((i) => i.id));
  const named = (ids: readonly string[]): string[] => ids.filter((id) => known.has(id));
  const upper = named(stored.slice(0, at));
  const lower = named(stored.slice(at + 1));
  const placed = new Set([...upper, ...lower]);
  return {
    top: [...upper, ...top.map((i) => i.id).filter((id) => !placed.has(id))],
    bottom: [...lower, ...bottom.map((i) => i.id).filter((id) => !placed.has(id))],
  };
}

export function zoneSequence(zones: RailZoneIds): string[] {
  return [...zones.top, RAIL_SPLIT, ...zones.bottom];
}

export function splitSequence(sequence: readonly string[]): RailZoneIds {
  const at = sequence.indexOf(RAIL_SPLIT);
  return at === -1 ? { top: [...sequence], bottom: [] } : { top: sequence.slice(0, at), bottom: sequence.slice(at + 1) };
}

export function slotGroup(stored: readonly string[], ids: readonly string[]): string[] {
  const drawn = new Set(ids);
  const queue = [...ids.filter((id) => stored.includes(id))];
  const out = stored.map((id) => (drawn.has(id) ? (queue.shift() as string) : id));
  const fresh = ids.filter((id) => !stored.includes(id));
  const at = out.indexOf(RAIL_SPLIT);
  out.splice(at === -1 ? out.length : at, 0, ...fresh);
  return out;
}
