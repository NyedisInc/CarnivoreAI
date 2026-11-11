const wakes = new Map<string, () => void>();

export function carryWake(tab: string, wake: () => void): void {
  wakes.set(tab, wake);
}

export function takeWake(tab: string): (() => void) | undefined {
  const wake = wakes.get(tab);
  wakes.delete(tab);
  return wake;
}
