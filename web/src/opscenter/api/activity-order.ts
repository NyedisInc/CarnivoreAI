import type { ActivityEntry } from './activity.svelte';

export function newestFirst(lines: readonly ActivityEntry[]): ActivityEntry[] {
  return lines
    .map((line, index) => ({ line, index }))
    .sort((a, b) => b.line.at - a.line.at || b.index - a.index)
    .map((entry) => entry.line);
}
