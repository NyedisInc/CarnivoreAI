
export type FocusEntry =
    | { kind: 'session'; id: string; tmuxName: string }
    | { kind: 'layout'; uuid: string };

export const FOCUS_HISTORY_CAP = 50;

export function sameEntry(a: FocusEntry | undefined, b: FocusEntry | undefined): boolean {
    if (!a || !b || a.kind !== b.kind) return false;
    return a.kind === 'session' ? a.id === (b as { id: string }).id : a.uuid === (b as { uuid: string }).uuid;
}

export interface FocusHistory {
    visit(entry: FocusEntry): void;
    step(dir: -1 | 1, isLive: (entry: FocusEntry) => boolean): FocusEntry | null;
    entries(): readonly FocusEntry[];
    cursor(): number;
    onChange(fn: () => void): () => void;
}

export function createFocusHistory(cap: number = FOCUS_HISTORY_CAP): FocusHistory {
    let list: FocusEntry[] = [];
    let pos = -1;
    let arriving: FocusEntry | null = null;
    const listeners = new Set<() => void>();
    const changed = (): void => { for (const fn of listeners) fn(); };
    return {
        visit(entry) {
            if (arriving && sameEntry(arriving, entry)) { arriving = null; return; }
            arriving = null;
            if (sameEntry(list[pos], entry)) return;
            list = list.slice(0, pos + 1).filter((e) => !sameEntry(e, entry));
            list.push(entry);
            if (list.length > cap) list = list.slice(list.length - cap);
            pos = list.length - 1;
            changed();
        },
        step(dir, isLive) {
            for (let i = pos + dir; i >= 0 && i < list.length; i += dir) {
                const entry = list[i];
                if (!entry || !isLive(entry)) continue;
                pos = i;
                arriving = entry;
                changed();
                return entry;
            }
            return null;
        },
        entries: () => list,
        cursor: () => pos,
        onChange(fn) { listeners.add(fn); return () => { listeners.delete(fn); }; },
    };
}

export const focusHistory: FocusHistory = createFocusHistory();
