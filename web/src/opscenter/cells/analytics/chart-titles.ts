const KEY = 'carnivore.analytics.titles';
export const TITLES_MAX = 200;

let memory: Record<string, string> | null = null;

function store(): Record<string, string> {
  if (memory) return memory;
  memory = {};
  try {
    const parsed = JSON.parse(globalThis.localStorage?.getItem(KEY) ?? 'null') as Record<string, unknown> | null;
    if (parsed && typeof parsed === 'object') for (const [id, title] of Object.entries(parsed)) if (typeof title === 'string') memory[id] = title;
  } catch {
  }
  return memory;
}

export function readChartTitle(id: string): string | null {
  return store()[id] || null;
}

export function rememberChartTitle(id: string, title: string | null | undefined): void {
  if (!title) return;
  const known = store();
  if (known[id] === title) return;
  delete known[id];
  known[id] = title;
  for (const old of Object.keys(known).slice(0, Math.max(0, Object.keys(known).length - TITLES_MAX))) delete known[old];
  try {
    globalThis.localStorage?.setItem(KEY, JSON.stringify(known));
  } catch {
  }
}

export function resetChartTitles(): void {
  memory = null;
}
