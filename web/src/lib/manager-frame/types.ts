
export interface ManagerItem {
    readonly id: string;
    readonly name: string;
    readonly brief?: string | null;
    readonly meta?: string | null;
    readonly marks?: readonly string[];
    readonly enabled?: boolean | null;
    readonly removeBlocked?: string | null;
    readonly icon?: string;
    readonly imagePath?: string;
    readonly iconFamilies?: readonly string[];
    readonly tags?: readonly string[];
    readonly byline?: string | null;
    readonly iconSvg?: string;
    readonly status?: { readonly label: string; readonly tone: 'on' | 'off' | 'warn' };
    readonly metric?: string | null;
    readonly corner?: readonly string[];
    readonly starred?: boolean;
    readonly chips?: readonly ManagerChip[];
}

export interface ManagerChip {
    readonly id: string;
    readonly label: string;
    readonly icon?: string;
    readonly svg?: string;
}

export interface ManagerFilter {
    readonly id: string;
    readonly label: string;
    readonly on: boolean;
    readonly test: (item: ManagerItem) => boolean;
}

export type ManagerStatus =
    | { readonly kind: 'loading' }
    | { readonly kind: 'ready' }
    | { readonly kind: 'error'; readonly message: string };

export interface ManagerToggleState {
    readonly busy: boolean;
    readonly error: string | null;
}

export interface ManagerExport {
    readonly filename: string;
    readonly document: unknown;
}

export interface ManagerActionState {
    readonly busy: boolean;
    readonly error: string | null;
    readonly exported: string | null;
}

export interface ManagerAdapter {
    list(): Promise<readonly ManagerItem[]>;
    setEnabled?(id: string, enabled: boolean): Promise<ManagerItem>;
    exportItem?(id: string): Promise<ManagerExport>;
    remove?(id: string): Promise<void>;
}
