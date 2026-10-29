import { refusalKey } from '../../../../client/js/labels/skill.js';

export const UNCONFIGURED_CODE = 'email_auth_not_configured';

export const MAX_EMAIL_CHARS = 254;

export const MAX_CODE_CHARS = 16;

export type EmailStep = 'address' | 'code';

export function stepAfterRefusal(code: string | null | undefined): EmailStep {
    return code === 'code_mismatch' || code === 'bad_code' ? 'code' : 'address';
}

export function isEmailUnconfigured(code: string | null | undefined): boolean {
    return code === UNCONFIGURED_CODE;
}

export function secondsLeft(deadline: number, now: number): number {
    if (!Number.isFinite(deadline) || !Number.isFinite(now)) return 0;
    return Math.max(0, Math.ceil((deadline - now) / 1000));
}

/* reads as broken */
export function minutesOf(seconds: number): number {
    if (!Number.isFinite(seconds) || seconds <= 0) return 1;
    return Math.max(1, Math.floor(seconds / 60));
}

export function looksLikeAddress(value: string): boolean {
    const address = value.trim();
    if (!address || address.length > MAX_EMAIL_CHARS) return false;
    if (/\s/.test(address)) return false;
    const [local, domain, ...rest] = address.split('@');
    return rest.length === 0 && !!local && !!domain;
}

export function looksLikeCode(value: string): boolean {
    const code = value.trim();
    return code.length > 0 && code.length <= MAX_CODE_CHARS && /^[0-9]+$/.test(code);
}

export function emailRefusalKey(code: string | null | undefined): string {
    return refusalKey(code);
}
