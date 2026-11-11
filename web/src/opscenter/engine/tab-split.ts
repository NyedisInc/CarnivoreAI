
export function freeSlot(taken: readonly string[], candidates: readonly string[]): string | null {
  return candidates.find((id) => id.startsWith('terminal:') && !taken.includes(id)) ?? null;
}
