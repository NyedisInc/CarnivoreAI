
export const FOLD_MEMORY_MAX = 200;

const chosen = new Map<string, boolean>();
const leaders = new Map<string, string>();

function trim(map: Map<string, unknown>): void {
  while (map.size > FOLD_MEMORY_MAX) {
    const oldest = map.keys().next().value;
    if (oldest === undefined) return;
    map.delete(oldest);
  }
}

export function wasFolded(key: string): boolean {
  const own = chosen.get(key);
  if (own !== undefined) return own;
  const leader = leaders.get(key);
  return leader !== undefined && chosen.get(leader) === true;
}

export function rememberFolded(key: string, folded: boolean): void {
  chosen.delete(key);
  chosen.set(key, folded);
  trim(chosen);
}

export function follow(key: string, leader: string): void {
  if (leaders.get(key) === leader) return;
  leaders.delete(key);
  chosen.delete(key);
  leaders.set(key, leader);
  trim(leaders);
}
