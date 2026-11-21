import { APP_CHORDS } from '../app-keys/chords';
import { effectiveAppChords, registryId } from '../app-keys/effective-chords';
import type { KeymapOverrides } from '../keymap/keymap-overrides';
import type { KeyboardFamily } from '../keymap/keymap-view';
import { keymapStore } from '../keymap/keymap-store.svelte';
import { onMac } from '../palette/palette-host';
import { hostWindow } from '../sessions/env';

export const GO_KEY_ACTIONS = ['history.back', 'history.forward'] as const;

export type GoKeys = Record<(typeof GO_KEY_ACTIONS)[number], string[]>;

interface GoKeysBridge { goKeys?: (keys: GoKeys) => void }

export function goKeyChords(overrides: KeymapOverrides, family: KeyboardFamily = onMac() ? 'mac' : 'other'): GoKeys {
    const table = effectiveAppChords(APP_CHORDS, overrides, family);
    const out = {} as GoKeys;
    for (const id of GO_KEY_ACTIONS) out[id] = table.filter((c) => registryId(c.id) === id).map((c) => c.accelerator);
    return out;
}

let started = false;

export function startGoKeys(): void {
    const bridge = (hostWindow() as { carnivoreDesktop?: GoKeysBridge } | undefined)?.carnivoreDesktop;
    if (started || !bridge || typeof bridge.goKeys !== 'function') return;
    started = true;
    keymapStore.start();
    $effect.root(() => {
        $effect(() => {
            bridge.goKeys?.(goKeyChords(keymapStore.overrides));
        });
    });
}
