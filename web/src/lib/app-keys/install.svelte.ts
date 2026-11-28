import { auth } from '../../opscenter/api/auth.svelte';
import { primarySessionId } from '../../opscenter/api/host';
import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
import { layoutMode } from '../../opscenter/layouts/mode.svelte';
import { focusHistory } from '../focus-history/focus-history';
import { APP_CHORDS } from './chords';
import { keymapStore } from '../keymap/keymap-store.svelte';
import { drawerRows } from '../palette/palette-sources';
import { onMac } from '../palette/palette-host';
import { pluginsStore } from '../plugins/store.svelte';
import { effectiveChordsWithPlugins } from './effective-chords';
import { installAppKeys } from './router';

let installed = false;

function currentSessionRef(): string | null {
    const id = primarySessionId();
    if (!id) return null;
    const row = drawerRows().find((r) => r.session_id === id || r.session_uuid === id);
    return String(row?.session_uuid || row?.session_id || row?.name || id) || null;
}

export function installAppChords(): void {
    if (installed || typeof document === 'undefined') return;
    installed = true;
    keymapStore.start();
    installAppKeys(
        () => effectiveChordsWithPlugins(APP_CHORDS, keymapStore.overrides, onMac() ? 'mac' : 'other', currentSessionRef),
        document,
    );
    globalThis.addEventListener(PRIMARY_BIND_EVENT, (event) => {
        const detail = (event as CustomEvent<{ sessionId?: string; tmuxName?: string }>).detail;
        const id = String(detail?.sessionId ?? '').trim();
        if (id) focusHistory.visit({ kind: 'session', id, tmuxName: String(detail?.tmuxName ?? '') });
    });
    $effect.root(() => {
        $effect(() => {
            if (auth.state === 'signed-out') return;
            return pluginsStore.acquire({ includeSlots: true });
        });
        $effect(() => {
            const uuid = layoutMode.uuid;
            if (uuid) focusHistory.visit({ kind: 'layout', uuid });
        });
    });
}
