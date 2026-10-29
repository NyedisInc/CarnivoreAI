
export const TERMINAL_APPS = ['ghostty', 'iterm2', 'terminal', 'kitty', 'wezterm', 'custom'] as const;

export type TerminalApp = (typeof TERMINAL_APPS)[number];

export interface DesktopPrefValues {
    desktop_banners: boolean;
    desktop_banner_hide_command: boolean;
    desktop_notify_asks_only: boolean;
    desktop_hotkey: string;
    mac_option_is_meta: boolean;
    desktop_menu_bar_icon: boolean;
    desktop_terminal_app: TerminalApp;
    desktop_terminal_custom: string;
}

export type DesktopPrefField = keyof DesktopPrefValues;

export const DESKTOP_PREF_DEFAULTS: Readonly<DesktopPrefValues> = {
    desktop_banners: false,
    desktop_banner_hide_command: false,
    desktop_notify_asks_only: false,
    desktop_hotkey: 'Ctrl+Option+Cmd+C',
    mac_option_is_meta: false,
    desktop_menu_bar_icon: true,
    desktop_terminal_app: 'terminal',
    desktop_terminal_custom: '',
};

export interface DesktopPrefs {
    read<K extends DesktopPrefField>(field: K): DesktopPrefValues[K];
    write<K extends DesktopPrefField>(field: K, value: DesktopPrefValues[K] | null): Promise<string | null>;
    follow<K extends DesktopPrefField>(field: K, apply: (value: DesktopPrefValues[K]) => void): () => void;
}

interface Bridge {
    read(field: string, localReader: () => unknown): unknown;
    write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
    follow?(field: string, apply: (value: unknown) => void): () => void;
}

const SAVED = new Set(['committed', 'unchanged']);

function bridge(): Bridge | null {
    const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
    return found && typeof found.read === 'function' ? found : null;
}

export function valueOf<K extends DesktopPrefField>(field: K, stored: unknown): DesktopPrefValues[K] {
    const fallback = DESKTOP_PREF_DEFAULTS[field];
    return (typeof stored === typeof fallback && stored !== null ? stored : fallback) as DesktopPrefValues[K];
}

export const livePrefs: DesktopPrefs = {
    read: (field) => valueOf(field, bridge()?.read(field, () => null)),
    async write(field, value) {
        const found = bridge();
        if (!found) return 'unavailable';
        const result = (await found.write(field, value, () => {})) as { status?: string; detail?: string } | null;
        const status = result && typeof result.status === 'string' ? result.status : '';
        if (SAVED.has(status)) return null;
        return (result && result.detail) || status || 'the server did not answer';
    },
    follow(field, apply) {
        const found = bridge();
        if (!found || typeof found.follow !== 'function') return () => {};
        return found.follow(field, (value) => apply(valueOf(field, value)));
    },
};
