
export const FUZZY_PREF_KEY = 'carnivore.changelog.fuzzy';

export function readFuzzyPref(): boolean {
    try {
        return localStorage.getItem(FUZZY_PREF_KEY) === '1';
    } catch {
        return false;
    }
}

export function writeFuzzyPref(on: boolean): void {
    try {
        localStorage.setItem(FUZZY_PREF_KEY, on ? '1' : '0');
    } catch {
    }
}
