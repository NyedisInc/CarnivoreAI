let held = $state(false);
let watchers = 0;

function onKey(event: KeyboardEvent): void {
  held = event.shiftKey;
}

function onBlur(): void {
  held = false;
}

export const shiftKey = {
  get held(): boolean {
    return held;
  },
};

export function watchShift(): () => void {
  const target = globalThis as unknown as Window;
  if (watchers++ === 0) {
    target.addEventListener('keydown', onKey, true);
    target.addEventListener('keyup', onKey, true);
    target.addEventListener('blur', onBlur);
  }
  return () => {
    if (--watchers > 0) return;
    target.removeEventListener('keydown', onKey, true);
    target.removeEventListener('keyup', onKey, true);
    target.removeEventListener('blur', onBlur);
    held = false;
  };
}
