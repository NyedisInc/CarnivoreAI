
export function captureOpener(): HTMLElement | null {
  const active = typeof document !== 'undefined' ? document.activeElement : null;
  return active instanceof HTMLElement ? active : null;
}

export function restoreOpenerFocus(opener: HTMLElement | null): void {
  if (opener && typeof document !== 'undefined' && document.contains(opener)) opener.focus();
}
