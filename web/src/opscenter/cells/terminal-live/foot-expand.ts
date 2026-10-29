
export const FOOT_EXPANDED_KEY = 'carnivore.terminalFoot.expanded';

export function readFootExpanded(): boolean {
  try {
    return globalThis.localStorage?.getItem(FOOT_EXPANDED_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeFootExpanded(value: boolean): void {
  try {
    globalThis.localStorage?.setItem(FOOT_EXPANDED_KEY, value ? '1' : '0');
  } catch {
  }
}

export const GROW_SHARE = 0.5;
export const GROW_CAP_PX = 460;

export const SPLIT_MIN_WIDTH = 640;

export function growRoom(areaPx: number): number {
  if (!Number.isFinite(areaPx) || areaPx <= 0) return 0;
  return Math.min(GROW_CAP_PX, Math.floor(areaPx * GROW_SHARE));
}
