import { mountPanel, unmountPanel } from '../mount';
import { hostDocument } from '../sessions/env';
import TimerList from './TimerList.svelte';

export const TIMER_LIST_ID = 'timer-list-popup';

export function closeTimerList(): boolean {
    return unmountPanel(TIMER_LIST_ID);
}

export function openTimerList(anchor: HTMLElement, sessionId: string, name: string): boolean {
    const doc = hostDocument();
    if (!doc || !sessionId) return false;
    let host = doc.getElementById(TIMER_LIST_ID);
    if (!host) {
        host = doc.createElement('div');
        host.id = TIMER_LIST_ID;
        doc.body.appendChild(host);
    }
    const mounted = mountPanel(TIMER_LIST_ID, TimerList, {
        anchor,
        sessionId,
        name,
        onClose: () => void closeTimerList(),
    });
    return mounted !== null;
}
