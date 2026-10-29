
export function fullIndex<T>(list: readonly T[], isDrawn: (item: T) => boolean, drawnIndex: number): number {
  const drawn = list.filter(isDrawn);
  const at = Math.max(0, drawnIndex);
  if (drawn.length === 0) return Math.min(at, list.length);
  if (at >= drawn.length) return list.indexOf(drawn[drawn.length - 1] as T) + 1;
  return list.indexOf(drawn[at] as T);
}
