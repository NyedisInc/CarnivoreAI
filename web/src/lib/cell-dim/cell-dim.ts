const KEY = 'carnivore.cell_dim_percent';

export const DIM_MIN = 0;
export const DIM_MAX = 60;
export const DIM_DEFAULT = 20;

export function applyCellDim(percent: number): void {
  document.documentElement.style.setProperty('--oc-cell-dim', String(1 - percent / 100));
}

export function storedCellDim(): number {
  try {
    const raw = Number(localStorage.getItem(KEY));
    if (localStorage.getItem(KEY) !== null && Number.isFinite(raw)) return Math.min(DIM_MAX, Math.max(DIM_MIN, raw));
  } catch {
  }
  return DIM_DEFAULT;
}

export function setCellDim(percent: number): void {
  applyCellDim(percent);
  try {
    localStorage.setItem(KEY, String(percent));
  } catch {
  }
}

export function applyStoredCellDim(): void {
  try {
    if (localStorage.getItem(KEY) === null) return;
  } catch {
    return;
  }
  applyCellDim(storedCellDim());
}
