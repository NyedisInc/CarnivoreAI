/* the mockup frame */

const MIN_SCALE = 0.1;

export function fitScale(viewport: number, room: number): number {
  return room <= 0 || viewport <= 0 ? 1 : Math.min(1, Math.max(MIN_SCALE, room / viewport));
}
