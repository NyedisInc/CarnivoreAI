
import { bridge, followPreference, savePreference } from '../zone-shell/preference-field';

export const TOAST_MODE_FIELD = 'toast_mode';

export const TOAST_MODES = ['compact', 'detailed'] as const;

export type ToastMode = (typeof TOAST_MODES)[number];

export function asMode(value: unknown): ToastMode {
    return value === 'detailed' ? 'detailed' : 'compact';
}

export function readToastMode(): ToastMode {
    return asMode(bridge()?.read(TOAST_MODE_FIELD, () => 'compact'));
}

export function saveToastMode(mode: ToastMode): Promise<string | null> {
    return savePreference(TOAST_MODE_FIELD, mode);
}

/* there is nothing */
export function followToastMode(apply: (mode: ToastMode) => void): () => void {
    return followPreference(TOAST_MODE_FIELD, asMode, apply);
}
