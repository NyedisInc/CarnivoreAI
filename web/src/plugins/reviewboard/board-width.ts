
export const WIDTH_KEY = 'carnivore.reviewboard.canvasFullWidth';

export function readFullWidth(): boolean {
  try {
    return localStorage.getItem(WIDTH_KEY) === '1';
  } catch {
    return false;
  }
}

export function writeFullWidth(full: boolean): void {
  try {
    if (full) localStorage.setItem(WIDTH_KEY, '1');
    else localStorage.removeItem(WIDTH_KEY);
  } catch {
  }
}
