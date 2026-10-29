/* The file drawer's */
import { readFlag, writeFlag } from '../ui/prefs.svelte';

export const HIDE_DOT_KEY = 'carnivore.files.hideDotFiles';

export const HIDE_IGNORED_KEY = 'carnivore.files.hideIgnored';

export type IgnoreStatus = 'unknown' | 'ok' | 'unavailable';

export interface DrawerPrefs {
    hideDot: boolean;
    hideIgnored: boolean;
}

export function readDrawerPrefs(): DrawerPrefs {
    return { hideDot: readFlag(HIDE_DOT_KEY), hideIgnored: readFlag(HIDE_IGNORED_KEY) };
}

export function writeDrawerPref(which: keyof DrawerPrefs, on: boolean): void {
    writeFlag(which === 'hideDot' ? HIDE_DOT_KEY : HIDE_IGNORED_KEY, on);
}
