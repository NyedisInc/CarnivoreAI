
export const WELCOME_FIELD = 'account_welcome_seen';

export interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
}
interface Prefs {
    status?: () => string;
    HYDRATED?: string;
}

export function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

export function prefsHydrated(): boolean {
    const prefs = (globalThis as { Preferences?: Prefs }).Preferences;
    return !!prefs && typeof prefs.status === 'function' && prefs.status() === (prefs.HYDRATED ?? 'hydrated');
}

export function readWelcomeSeen(): boolean {
    return bridge()?.read(WELCOME_FIELD, () => null) === true;
}

export async function writeWelcomeSeen(): Promise<void> {
    const found = bridge();
    if (!found) return;
    const result = (await found.write(WELCOME_FIELD, true, () => {})) as { status?: string; detail?: string } | null;
    const status = result?.status ?? '';
    if (status !== 'committed' && status !== 'unchanged') {
        console.warn('[welcome] could not save the seen flag', status, result?.detail ?? '');
    }
}
