import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
import { layoutMode } from '../../opscenter/layouts/mode.svelte';
import { focusHistory } from '../focus-history/focus-history';
import { APP_CHORDS } from './chords';
import { keymapStore } from '../keymap/keymap-store.svelte';
import { onMac } from '../palette/palette-host';
import { effectiveAppChords } from './effective-chords';
import { installAppKeys } from './router';

let installed = false;

export function installAppChords(): void {
    if (installed || typeof document === 'undefined') return;
    installed = true;
    keymapStore.start();
    installAppKeys(() => effectiveAppChords(APP_CHORDS, keymapStore.overrides, onMac() ? 'mac' : 'other'), document);
    globalThis.addEventListener(PRIMARY_BIND_EVENT, (event) => {
        const detail = (event as CustomEvent<{ sessionId?: string; tmuxName?: string }>).detail;
        const id = String(detail?.sessionId ?? '').trim();
        if (id) focusHistory.visit({ kind: 'session', id, tmuxName: String(detail?.tmuxName ?? '') });
    });
    $effect.root(() => {
        $effect(() => {
            const uuid = layoutMode.uuid;
            if (uuid) focusHistory.visit({ kind: 'layout', uuid });
        });
    });
}
