import { nextKey } from '../zone-shell/key-nav';

export const CUE_MS = 1800;

export function railKeyTarget(key: string, ids: readonly string[], current: string | null): string | null {
  return nextKey(key, ids, current, 'both', true);
}

export interface CueReading {
  id: string;
  count: number;
}

export class BadgeCue {
  id = $state<string | null>(null);
  #seen = new Map<string, number>();
  #timer: ReturnType<typeof setTimeout> | null = null;

  note(readings: readonly CueReading[]): void {
    let grew: string | null = null;
    for (const { id, count } of readings) {
      if (count > (this.#seen.get(id) ?? 0)) grew = id;
      this.#seen.set(id, count);
    }
    for (const id of [...this.#seen.keys()]) if (!readings.some((r) => r.id === id)) this.#seen.delete(id);
    if (grew === null) return;
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.id = grew;
    this.#timer = setTimeout(() => {
      this.id = null;
      this.#timer = null;
    }, CUE_MS);
  }

  dispose(): void {
    if (this.#timer !== null) clearTimeout(this.#timer);
    this.#timer = null;
  }
}
