import { chordsOf } from '../../../../client/js/keymap/effective.js';
import { normalize } from '../../../../client/js/keymap/chord.js';
import { scopesOverlap } from '../../../../client/js/keymap/scopes.js';
import { refusal } from '../../../../client/js/keymap/protected.js';
import type { KeyboardFamily, KeymapAction } from './keymap-view';

export type ChordMap = Record<string, string[]>;

export interface KeymapOverrides {
    mac?: ChordMap;
    other?: ChordMap;
    mouse?: ChordMap;
}

export const MIDDLE = 'middle';

export function readOverrides(value: unknown): KeymapOverrides {
    const out: KeymapOverrides = {};
    if (!value || typeof value !== 'object') return out;
    for (const key of ['mac', 'other', 'mouse'] as const) {
        const raw = (value as Record<string, unknown>)[key];
        if (!raw || typeof raw !== 'object') continue;
        const map: ChordMap = {};
        for (const [id, list] of Object.entries(raw as Record<string, unknown>)) {
            if (Array.isArray(list) && list.every((c) => typeof c === 'string')) map[id] = key === 'mouse' ? (list as string[]) : (list as string[]).map(normalize).filter((c) => c !== '');
        }
        if (Object.keys(map).length > 0) out[key] = map;
    }
    return out;
}

export function withChords(overrides: KeymapOverrides, family: KeyboardFamily | 'mouse', id: string, chords: readonly string[]): KeymapOverrides {
    return { ...overrides, [family]: { ...(overrides[family] ?? {}), [id]: [...chords] } };
}

export function withoutChords(overrides: KeymapOverrides, family: KeyboardFamily | 'mouse', id: string): KeymapOverrides {
    const { [id]: _gone, ...rest } = overrides[family] ?? {};
    const next: KeymapOverrides = { ...overrides };
    if (Object.keys(rest).length > 0) next[family] = rest;
    else delete next[family];
    return next;
}

export const isEmpty = (overrides: KeymapOverrides): boolean => Object.keys(overrides).length === 0;

export interface Verdict {
    refused: string | null;
    /* at the same time */
    clashes: KeymapAction[];
    overlaps: KeymapAction[];
}

/* at the same time */
export function judge(action: KeymapAction, chord: string, family: KeyboardFamily, all: readonly KeymapAction[], overrides: KeymapOverrides): Verdict {
    const refused = refusal(family, chord, action.scope, all);
    const hasCmd = chord.split('+').includes('cmd');
    const holders = all.filter((a) => a.id !== action.id && a.category !== 'standard' && (chordsOf(a, family, overrides) as string[]).includes(chord));
    const shared = (a: KeymapAction): boolean => a.mayShare && action.mayShare;
    return {
        refused,
        clashes: holders.filter((a) => !shared(a) && (a.scope === action.scope || scopesOverlap(a.scope, action.scope, hasCmd))),
        overlaps: holders.filter(shared),
    };
}

export const canSave = (verdict: Verdict): boolean => verdict.refused === null && verdict.clashes.length === 0;
