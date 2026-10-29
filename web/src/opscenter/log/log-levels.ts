
import { LOG_LEVELS, type LogLevel } from './types';

export { LOG_LEVELS, type LogLevel };

export const LOG_LEVELS_KEY = 'carnivore.developer.log.levels';

export const DEFAULT_LEVELS: readonly LogLevel[] = ['error'];

export function readLevels(): LogLevel[] {
  try {
    const raw = globalThis.localStorage?.getItem(LOG_LEVELS_KEY);
    if (raw === null || raw === undefined) return [...DEFAULT_LEVELS];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [...DEFAULT_LEVELS];
    return LOG_LEVELS.filter((level) => parsed.includes(level));
  } catch {
    return [...DEFAULT_LEVELS];
  }
}

export function writeLevels(levels: readonly LogLevel[]): void {
  try {
    globalThis.localStorage?.setItem(LOG_LEVELS_KEY, JSON.stringify(levels));
  } catch {
  }
}

export function toggleLevel(levels: readonly LogLevel[], level: LogLevel): LogLevel[] {
  return LOG_LEVELS.filter((l) => (l === level ? !levels.includes(l) : levels.includes(l)));
}
