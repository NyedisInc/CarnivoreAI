import type { RailEdge } from '../session-rail/rail-model';

export function pinKey(edge: RailEdge): string {
  return `carnivore.session.rail.pin.${edge}`;
}

const SECTION_SLOTS = 2;

interface EdgeLocks {
  tabs: Record<string, number>;
  legacy: (number | null)[];
}

function asRow(raw: unknown): number | null {
  return typeof raw === 'number' && Number.isInteger(raw) && raw > 0 ? raw : null;
}

function noLocks(): EdgeLocks {
  return { tabs: {}, legacy: Array<number | null>(SECTION_SLOTS).fill(null) };
}

function readLocks(edge: RailEdge): EdgeLocks {
  const locks = noLocks();
  try {
    const stored = JSON.parse(localStorage.getItem(pinKey(edge)) ?? 'null') as { row?: unknown; rows?: unknown; tabs?: unknown } | null;
    if (stored?.tabs && typeof stored.tabs === 'object' && !Array.isArray(stored.tabs)) {
      for (const [key, raw] of Object.entries(stored.tabs)) {
        const row = asRow(raw);
        if (row !== null) locks.tabs[key] = row;
      }
    }
    if (Array.isArray(stored?.rows)) locks.legacy = locks.legacy.map((_, i) => asRow((stored!.rows as unknown[])[i]));
    else if (asRow(stored?.row) !== null) locks.legacy = locks.legacy.map(() => asRow(stored!.row));
    return locks;
  } catch {
    return noLocks();
  }
}

function writeLocks(edge: RailEdge, locks: EdgeLocks): void {
  try {
    const waiting = locks.legacy.some((row) => row !== null);
    if (Object.keys(locks.tabs).length === 0 && !waiting) localStorage.removeItem(pinKey(edge));
    else localStorage.setItem(pinKey(edge), JSON.stringify(waiting ? { tabs: locks.tabs, rows: locks.legacy } : { tabs: locks.tabs }));
  } catch {
  }
}

class PanelPins {
  #pins = $state<Record<RailEdge, EdgeLocks>>({ side: readLocks('side'), bottom: readLocks('bottom') });
  #files = 0;

  pinnedRow(edge: RailEdge, tab: string): number | null {
    return this.#pins[edge].tabs[tab] ?? null;
  }

  pinned(edge: RailEdge, tab?: string): boolean {
    return tab === undefined ? Object.keys(this.#pins[edge].tabs).length > 0 : this.pinnedRow(edge, tab) !== null;
  }

  rows(): number[] {
    return [...new Set([...Object.values(this.#pins.side.tabs), ...Object.values(this.#pins.bottom.tabs)])];
  }

  pin(edge: RailEdge, tab: string, row: number): void {
    const next = { ...this.#pins[edge], tabs: { ...this.#pins[edge].tabs, [tab]: row } };
    this.#pins[edge] = next;
    writeLocks(edge, next);
  }

  unpin(edge: RailEdge, tab?: string): void {
    const now = this.#pins[edge];
    if (tab === undefined ? !this.pinned(edge) && now.legacy.every((row) => row === null) : !(tab in now.tabs)) return;
    const next: EdgeLocks = tab === undefined ? noLocks() : { ...now, tabs: Object.fromEntries(Object.entries(now.tabs).filter(([key]) => key !== tab)) };
    this.#pins[edge] = next;
    writeLocks(edge, next);
  }

  adoptLegacy(edge: RailEdge, section: number, tab: string): boolean {
    const now = this.#pins[edge];
    const row = now.legacy[section] ?? null;
    if (row === null) return false;
    const next: EdgeLocks = { tabs: tab in now.tabs ? now.tabs : { ...now.tabs, [tab]: row }, legacy: now.legacy.map((one, i) => (i === section ? null : one)) };
    this.#pins[edge] = next;
    writeLocks(edge, next);
    return true;
  }

  get filesHeld(): boolean {
    return this.#files > 0;
  }

  holdFiles(): () => void {
    this.#files += 1;
    return () => {
      this.#files -= 1;
    };
  }

  reload(): void {
    this.#pins = { side: readLocks('side'), bottom: readLocks('bottom') };
  }
}

export const panelPins = new PanelPins();
