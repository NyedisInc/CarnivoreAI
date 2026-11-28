
export const READ_PAUSE_MS = 400;

let lastReadAt = 0;

export function readPaused(now: number = Date.now()): boolean {
  return now - lastReadAt < READ_PAUSE_MS;
}

export function startReadPause(now: number = Date.now()): void {
  lastReadAt = now;
}

export function resetReadPause(): void {
  lastReadAt = 0;
}
