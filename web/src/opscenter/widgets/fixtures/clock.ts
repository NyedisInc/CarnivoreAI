
export const FROZEN_NOW = Date.UTC(2026, 8, 30, 15, 0, 0);

export const MIN = 60;
export const HOUR = 60 * MIN;
export const DAY = 24 * HOUR;

export function ago(seconds: number): string {
  return new Date(FROZEN_NOW - seconds * 1000).toISOString();
}

export function epochAgo(seconds: number): number {
  return Math.round(FROZEN_NOW / 1000 - seconds);
}
