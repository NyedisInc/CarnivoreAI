/* the empty state */
import { mountPanel, unmountPanel } from '../mount';
import { hostDocument } from '../sessions/env';
import TerminalEmpty from './TerminalEmpty.svelte';

export const EMPTY_CONTAINER_ID = 'terminal-empty-state';

export const EMPTY_SCREEN_CLASS = 'terminal-screen--empty';

function terminalScreen(): HTMLElement | null {
    const doc = hostDocument();
    if (!doc || typeof doc.getElementById !== 'function') return null;
    return doc.getElementById('terminal-screen');
}

export function openTerminalEmpty(): boolean {
    const screen = terminalScreen();
    if (!screen) return false;
    screen.classList.add(EMPTY_SCREEN_CLASS);
    return mountPanel(EMPTY_CONTAINER_ID, TerminalEmpty as never, {}) !== null;
}

export function closeTerminalEmpty(): boolean {
    const screen = terminalScreen();
    const marked = !!screen && screen.classList.contains(EMPTY_SCREEN_CLASS);
    if (marked) screen!.classList.remove(EMPTY_SCREEN_CLASS);
    const unmounted = unmountPanel(EMPTY_CONTAINER_ID);
    return marked || unmounted;
}
