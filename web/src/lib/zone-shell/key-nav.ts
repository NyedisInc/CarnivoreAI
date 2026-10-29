
export type KeyAxis = 'x' | 'y' | 'both';

export function isMenuKey(event: { key: string; shiftKey: boolean }): boolean {
  return event.key === 'ContextMenu' || (event.key === 'F10' && event.shiftKey);
}

export function nextKey(key: string, ids: readonly string[], current: string | null, axis: KeyAxis, wrap: boolean): string | null {
  if (ids.length === 0) return null;
  if (key === 'Home') return ids[0] ?? null;
  if (key === 'End') return ids[ids.length - 1] ?? null;
  const back = (axis !== 'y' && key === 'ArrowLeft') || (axis !== 'x' && key === 'ArrowUp');
  const forward = (axis !== 'y' && key === 'ArrowRight') || (axis !== 'x' && key === 'ArrowDown');
  if (!back && !forward) return null;
  const at = current === null ? -1 : ids.indexOf(current);
  if (at < 0) return ids[0] ?? null;
  const step = at + (back ? -1 : 1);
  if (step >= 0 && step < ids.length) return ids[step] ?? null;
  return wrap ? (ids[(step + ids.length) % ids.length] ?? null) : null;
}
