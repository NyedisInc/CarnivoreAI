
export interface DesktopLogin {
    engine: boolean | null;
    window: boolean | null;
    background: boolean | null;
}

export type NotificationState = 'allowed' | 'not_asked' | 'denied' | 'unknown';

export interface DesktopHotkey {
    registered: boolean | null;
    error: string | null;
}

export interface DesktopState {
    login: DesktopLogin;
    notifications: { state: NotificationState; waiting?: boolean; banners?: { posting: boolean } };
    hotkey: DesktopHotkey;
    network?: { tls: 'secure' | 'insecure' | 'unknown' };
}

export interface OpenInTerminalResult {
    opened: boolean;
    error: string | null;
    reason: 'ok' | 'remote' | 'not_running' | 'cancelled' | 'failed';
}

export interface FolderTargetResult {
    ok: boolean;
    reason: 'ok' | 'remote' | 'missing' | 'no_editor' | 'cancelled' | 'failed';
    error: string | null;
}

export interface DesktopBridge {
    contract?: number;
    capabilities?: readonly string[];
    desktopState?: () => Promise<DesktopState>;
    setLoginItem?: (which: 'engine' | 'window' | 'background', enabled: boolean) => Promise<DesktopLogin>;
    requestNotifications?: () => Promise<{ state: NotificationState; waiting?: boolean }>;
    openNotificationSettings?: () => Promise<void>;
    openFocusSettings?: () => Promise<'focus' | 'notifications' | null>;
    openInTerminal?: (sessionId: string) => Promise<OpenInTerminalResult>;
    openSessionWindow?: (rowId: string) => Promise<boolean>;
    focusSessionWindow?: (rowId: string) => Promise<boolean>;
    showInMain?: (rowId: string) => Promise<boolean>;
    revealById?: (id: string) => Promise<FolderTargetResult>;
    openInEditor?: (id: string) => Promise<FolderTargetResult>;
    raiseWindow?: () => Promise<boolean>;
}

export function desktopBridge(): DesktopBridge | null {
    const found = (globalThis as { carnivoreDesktop?: unknown }).carnivoreDesktop;
    return found && typeof found === 'object' ? (found as DesktopBridge) : null;
}

export function hasDesktopCapability(name: keyof DesktopBridge & string, bridge: DesktopBridge | null = desktopBridge()): boolean {
    return !!bridge && Array.isArray(bridge.capabilities) && bridge.capabilities.includes(name) && typeof bridge[name] === 'function';
}
