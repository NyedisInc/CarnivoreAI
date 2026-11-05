import { formatChord, parse } from '../../../../client/js/keymap/chord.js';
import type { KeymapOverrides } from '../keymap/keymap-overrides';
import type { KeyboardFamily } from '../keymap/keymap-view';
import type { AppChord } from './router';

export const registryId = (chordId: string): string => (chordId === 'palette.open.other' ? 'palette.open' : chordId);

function entryFor(built: AppChord, chord: string): AppChord {
    const { mods, key } = parse(chord) as { mods: string[]; key: string };
    return {
        ...built,
        key,
        meta: mods.includes('cmd'),
        ctrl: mods.includes('ctrl'),
        alt: mods.includes('alt'),
        shift: mods.includes('shift'),
        anyShift: key.length === 1 && !/[a-z0-9]/.test(key),
        accelerator: chord,
        keys: formatChord(chord) as string,
    };
}

export function effectiveAppChords(built: readonly AppChord[], overrides: KeymapOverrides, family: KeyboardFamily): AppChord[] {
    const mine = overrides[family] ?? {};
    const out: AppChord[] = [];
    const done = new Set<string>();
    for (const chord of built) {
        const id = registryId(chord.id);
        const stored = mine[id];
        if (!Array.isArray(stored)) {
            out.push(chord);
            continue;
        }
        if (done.has(id)) continue;
        const carrier = family === 'other' ? (built.find((c) => c.id === `${id}.other`) ?? chord) : (built.find((c) => registryId(c.id) === id) ?? chord);
        done.add(id);
        for (const stored1 of stored) out.push(entryFor(carrier, stored1));
    }
    return out;
}
