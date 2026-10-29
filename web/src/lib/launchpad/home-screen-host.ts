import { mountPanel, unmountPanel } from '../mount';
import { SCREEN_ID } from './home-anchors';
import { hostDocument } from '../sessions/env';
import OpscenterApp from '../../opscenter/App.svelte';

let screenEl: HTMLElement | null = null;

export function launchpadScreen(): HTMLElement | null {
    return screenEl;
}

export function mountHomeScreen(): HTMLElement | null {
    const target = hostDocument()?.getElementById(SCREEN_ID) ?? null;
    if (!target) {
        console.error('CloudeWeb: #' + SCREEN_ID + ' is not in the document, the home screen cannot mount');
        return null;
    }
    if (mountPanel(SCREEN_ID, OpscenterApp) === null) return null;
    screenEl = target;
    return target;
}

/* the home screen */
export function unmountHomeScreen(): void {
    unmountPanel(SCREEN_ID);
    screenEl = null;
}
