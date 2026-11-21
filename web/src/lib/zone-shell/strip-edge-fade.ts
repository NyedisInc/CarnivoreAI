
export type EdgeFade = 'start' | 'end' | 'both' | null;

const REST_SLACK_PX = 1;

export function edgeFade(scrolled: number, visible: number, total: number): EdgeFade {
  const before = scrolled > REST_SLACK_PX;
  const after = total - visible - scrolled > REST_SLACK_PX;
  if (before && after) return 'both';
  if (before) return 'start';
  return after ? 'end' : null;
}
