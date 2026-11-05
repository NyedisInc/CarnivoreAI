import { layouts } from '../layouts-bridge/api.svelte';
import { sessions } from '../../opscenter/api/sessions.svelte';
import { focusHistory, sameEntry, type FocusEntry, type FocusHistory } from '../focus-history/focus-history';
import { isLive } from '../app-keys/chords';
import { goTo } from '../nav-items/nav-items';
import { t } from '../i18n/index.svelte';
import { hostWindow } from '../sessions/env';

export const GO_RECENT_MAX = 10;

export function recentPlaces(history: FocusHistory, live: (e: FocusEntry) => boolean): FocusEntry[] {
    const all = history.entries();
    const here = all[history.cursor()];
    const out: FocusEntry[] = [];
    for (let i = all.length - 1; i >= 0 && out.length < GO_RECENT_MAX; i -= 1) {
        const entry = all[i];
        if (entry && !sameEntry(entry, here) && live(entry)) out.push(entry);
    }
    return out;
}

export function placeLabel(entry: FocusEntry): string {
    if (entry.kind === 'layout') {
        const name = layouts.data?.find((l) => l.layout_uuid === entry.uuid)?.name?.trim();
        return name || t('menubar.menu.unnamed_layout');
    }
    const row = sessions.data?.find((r) => r.session?.id === entry.id);
    return row?.label?.trim() || entry.tmuxName || entry.id;
}

let published: FocusEntry[] = [];

export function goRecent(n: number): void {
    const entry = published[n];
    if (!entry || !isLive(entry)) return;
    void goTo(entry.kind === 'layout' ? entry : { kind: 'session', id: entry.id, tmuxName: entry.tmuxName });
}

interface GoBridge { goRecent?: (labels: string[]) => void }

let started = false;

export function startGoMenu(): void {
    const bridge = (hostWindow() as { carnivoreDesktop?: GoBridge } | undefined)?.carnivoreDesktop;
    if (started || !bridge || typeof bridge.goRecent !== 'function') return;
    started = true;
    focusHistory.onChange(() => {
        published = recentPlaces(focusHistory, isLive);
        bridge.goRecent?.(published.map(placeLabel));
    });
}
