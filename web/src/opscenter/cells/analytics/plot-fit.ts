/* height: 70px min-height: 7 */
export const MIN_PLOT_HEIGHT_PX = 70;

export function chartFits(plotHeight: number | null): boolean {
  return plotHeight !== null && plotHeight >= MIN_PLOT_HEIGHT_PX;
}

export function plotBoxHeight(band: HTMLElement): number {
  const own = band.clientHeight;
  const card = band.parentElement;
  if (!card) return own;
  const room = card.clientHeight - band.offsetTop - (parseFloat(getComputedStyle(band).marginBottom) || 0);
  return own >= MIN_PLOT_HEIGHT_PX ? Math.min(own, room) : Math.max(own, room);
}
