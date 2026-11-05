import { mountPanel, unmountPanel } from '../mount';
import Palette from './Palette.svelte';
import { PALETTE_CONTAINER } from './palette-actions';

let open = false;

export function closePalette(): void {
    if (!open) return;
    open = false;
    unmountPanel(PALETTE_CONTAINER);
}

export function togglePalette(mode: 'go' | 'actions' = 'go'): boolean {
    if (open) {
        closePalette();
        return true;
    }
    const restore = typeof document !== 'undefined' ? document.activeElement as HTMLElement | null : null;
    open = !!mountPanel(PALETTE_CONTAINER, Palette, {
        initial: mode === 'actions' ? '>' : '',
        onClose: () => {
            closePalette();
            if (restore && typeof restore.focus === 'function' && restore.isConnected) restore.focus();
        },
    });
    return true;
}

export function onMac(): boolean {
    const nav = globalThis.navigator as (Navigator & { userAgentData?: { platform?: string } }) | undefined;
    const platform = nav?.userAgentData?.platform || nav?.platform || '';
    return /mac|iphone|ipad/i.test(platform);
}
