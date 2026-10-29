import { hostWindow } from './env';

export interface NameableRow {
    label?: string | null;
    name?: string | null;
}

interface LegacySessionLabel {
    resolve(row: NameableRow): string;
    UNKNOWN: string;
    LABEL_MAX_CHARS?: number;
    validate?(value: string): { ok: boolean; reason?: string; value?: string };
}

export function legacySessionLabel(): LegacySessionLabel | null {
    const w = hostWindow() as unknown as
        { SessionLabel?: LegacySessionLabel } | undefined;
    return (w && w.SessionLabel) || null;
}

export function derivedDisplayName(tmuxName: string | null | undefined): string {
    const name = tmuxName || '';
    return name.startsWith('cloude_') ? name.slice('cloude_'.length) : name;
}

/* label: ' */
export function sessionDisplayLabel(row: NameableRow | null | undefined): string {
    const safe = row || {};
    const shared = legacySessionLabel();
    if (shared && typeof shared.resolve === 'function') {
        return shared.resolve(safe) || shared.UNKNOWN;
    }
    console.error('CloudeWeb: SessionLabel is not loaded, naming sessions by handle');
    const label = typeof safe.label === 'string' ? safe.label.trim() : '';
    if (label) return label;
    return derivedDisplayName(typeof safe.name === 'string' ? safe.name : '');
}
