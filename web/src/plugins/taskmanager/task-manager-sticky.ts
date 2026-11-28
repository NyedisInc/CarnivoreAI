
export const PROJECT_HEAD_HEIGHT_VAR = '--hd-phead-h';
export const STICK_TOP_VAR = '--hd-stick-top';
export const PROJECT_HEAD_HEIGHT_PX = 30;

export const TAIL_OWN_ROW_BELOW_PX = 440;

export const PROJECT_HEAD_HEIGHT_TWO_ROW_PX = 52;

export function projectHeadHeight(listWidth: number): number {
  return listWidth > 0 && listWidth < TAIL_OWN_ROW_BELOW_PX ? PROJECT_HEAD_HEIGHT_TWO_ROW_PX : PROJECT_HEAD_HEIGHT_PX;
}

function bars(count: number): string {
  return count === 0 ? '0px' : `calc(var(${PROJECT_HEAD_HEIGHT_VAR}) * ${count})`;
}

export function projectStick(index: number, total: number): { top: string; bottom: string } {
  return { top: bars(index), bottom: bars(Math.max(0, total - 1 - index)) };
}

export function sectionTop(headed: boolean, index: number): string {
  return headed ? bars(index + 1) : '0px';
}

export function projectScrollTop(naturalTop: number, index: number, headHeight: number): number {
  return Math.max(0, naturalTop - index * headHeight);
}

export function scrollProjectToTop(head: HTMLElement, reducedMotion: boolean): void {
  const scroller = head.closest<HTMLElement>('[data-task-manager-scroll]');
  if (!scroller) return;
  const heads = [...scroller.querySelectorAll<HTMLElement>('[data-task-manager-level="project"]')];
  const index = Math.max(0, heads.indexOf(head));
  const headHeight = head.offsetHeight;
  let barsBetween = 0;
  let before = head.previousElementSibling as HTMLElement | null;
  while (before && before.dataset.taskManagerLevel === 'project') {
    barsBetween += 1;
    before = before.previousElementSibling as HTMLElement | null;
  }
  const box = scroller.getBoundingClientRect();
  const base = before ? before.getBoundingClientRect().bottom - box.top + scroller.scrollTop : 0;
  const top = projectScrollTop(base + barsBetween * headHeight, index, headHeight);
  scroller.scrollTo({ top, behavior: reducedMotion ? 'auto' : 'smooth' });
}

export const ACCORDION_MIN_OPEN_SHARE = 1 / 3;

export function accordionStackFits(boxHeight: number, bars: number, headHeight: number): boolean {
  if (boxHeight <= 0) return true;
  return boxHeight - bars * headHeight >= boxHeight * ACCORDION_MIN_OPEN_SHARE;
}

export function stackSide(index: number, openIndex: number): 'top' | 'open' | 'bottom' {
  return index < openIndex ? 'top' : index === openIndex ? 'open' : 'bottom';
}
