
export type ChipKind = 'host' | 'project' | 'state';
export const CHIP_SIGILS: Readonly<Record<string, ChipKind>> = { '@': 'host', '#': 'project', ':': 'state' };

export interface Chip {
    kind: ChipKind;
    value: string;
}

export const STATES = ['waiting', 'working', 'idle', 'asleep', 'blocked', 'unread'] as const;
export type PaletteState = (typeof STATES)[number];

export interface ParsedQuery {
    mode: 'go' | 'actions' | 'deep';
    text: string;
    pending: { kind: ChipKind; value: string; raw: string } | null;
}

export function parseQuery(raw: string): ParsedQuery {
    const lead = raw.trimStart();
    const mode = lead.startsWith('>') ? 'actions' : lead.startsWith('?') ? 'deep' : 'go';
    const text = mode === 'go' ? raw : lead.slice(1);
    if (mode === 'deep') return { mode, text: text.trim(), pending: null };
    const last = /(^|\s)([@#:])(\S*)$/.exec(text);
    const pending = last ? { kind: CHIP_SIGILS[last[2]!]!, value: last[3]!.toLowerCase(), raw: last[2]! + last[3]! } : null;
    return { mode, text, pending };
}

export function commitChip(raw: string, known: Readonly<Record<ChipKind, readonly string[]>>): { chip: Chip; rest: string } | null {
    const q = parseQuery(raw);
    if (!q.pending) return null;
    const pool = known[q.pending.kind];
    const value = pool.find((v) => v === q.pending!.value) ?? pool.find((v) => v.startsWith(q.pending!.value));
    if (!value) return null;
    const cut = raw.length - q.pending.raw.length;
    return { chip: { kind: q.pending.kind, value }, rest: raw.slice(0, cut) };
}

export interface Filterable {
    host?: string;
    project?: string;
    states?: readonly string[];
}

export function passesChips(row: Filterable, chips: readonly Chip[]): boolean {
    for (const chip of chips) {
        if (chip.kind === 'host' && (row.host ?? '').toLowerCase() !== chip.value) return false;
        if (chip.kind === 'project' && (row.project ?? '').toLowerCase() !== chip.value) return false;
        if (chip.kind === 'state' && !(row.states ?? []).includes(chip.value)) return false;
    }
    return true;
}

export function rankText(parsed: ParsedQuery): string {
    return parsed.pending ? parsed.text.slice(0, parsed.text.length - parsed.pending.raw.length).trim() : parsed.text.trim();
}
