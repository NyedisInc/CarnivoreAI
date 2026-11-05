
export interface Span {
  start: number;
  end: number;
}

export function inSplitZone(area: Span, keysEnd: number | null, pos: number): boolean {
  const middle = area.start + (area.end - area.start) / 2;
  return pos >= Math.max(middle, keysEnd ?? area.start) && pos <= area.end;
}

export type SplitOffer = 'drop' | 'offer' | null;

export function splitOffer(area: Span, keysEnd: number | null, pos: number): SplitOffer {
  if (inSplitZone(area, keysEnd, pos)) return 'drop';
  const middle = area.start + (area.end - area.start) / 2;
  return keysEnd === null || keysEnd <= middle ? 'offer' : null;
}

export function keysEndOf(ends: readonly number[]): number | null {
  return ends.length === 0 ? null : Math.max(...ends);
}
