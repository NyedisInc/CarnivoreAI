
export function foldKey(id: number): string {
  return `carnivore.huddle.review.open.${id}`;
}

export function reviewOpen(id: number): boolean {
  try {
    return window.localStorage.getItem(foldKey(id)) === '1';
  } catch {
    return false;
  }
}

export function setReviewOpen(id: number, open: boolean): void {
  try {
    if (open) window.localStorage.setItem(foldKey(id), '1');
    else window.localStorage.removeItem(foldKey(id));
  } catch {
  }
}
