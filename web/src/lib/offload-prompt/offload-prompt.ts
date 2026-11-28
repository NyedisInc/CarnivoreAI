import { ApiError, errorCodeOf } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import { openModal } from '../modal';
import OffloadPrompt from './OffloadPrompt.svelte';
import { firstNotRestored, OFFLOADED_CODE, readOffloaded, restoreAllowed, restoreOffloaded, type OffloadedDetails, type OffloadTarget } from './offload-api';

export interface RefusalAnswer { status?: string; code?: string | null }

export const CANCELLED = Symbol('offload-restore-cancelled');

const FAILED_KEY = 'offload.prompt.err.failed';

const STATUS_KEYS: Readonly<Record<string, string>> = {
    conflict: 'offload.prompt.err.conflict',
    failed: FAILED_KEY,
    no_vault_point: 'offload.prompt.err.no_point',
    present_elsewhere: 'offload.prompt.err.present_elsewhere',
};

const CODE_KEYS: Readonly<Record<string, string>> = {
    vault_unavailable: 'offload.prompt.err.vault',
    cplug_disabled: 'offload.prompt.err.off',
};

export function isOffloadedAnswer(answer: unknown): boolean {
    return !!answer && typeof answer === 'object' && (answer as RefusalAnswer).code === OFFLOADED_CODE;
}

export function isOffloadedError(err: unknown): boolean {
    if (err instanceof ApiError) return err.code === OFFLOADED_CODE;
    return errorCodeOf((err as { body?: unknown } | null)?.body) === OFFLOADED_CODE;
}

async function restoreSentence(target: OffloadTarget): Promise<string> {
    try {
        const bad = firstNotRestored(await restoreOffloaded(target));
        return bad ? t(STATUS_KEYS[bad.status] ?? FAILED_KEY, { path: bad.path ?? '' }) : '';
    } catch (err) {
        const key = err instanceof ApiError && err.code ? CODE_KEYS[err.code] : undefined;
        if (key) return t(key);
        console.warn('OffloadPrompt: the restore was refused', err);
        return err instanceof Error && err.message ? err.message : t(FAILED_KEY);
    }
}

/* could not be read */
async function detailsOf(target: OffloadTarget): Promise<OffloadedDetails | null | undefined> {
    try {
        return await readOffloaded(target);
    } catch (err) {
        if (err instanceof ApiError && err.status === 404) return undefined;
        console.warn('OffloadPrompt: the offloaded details could not be read', err);
        return null;
    }
}

export async function canOfferRestore(target: OffloadTarget): Promise<boolean> {
    const details = await detailsOf(target);
    return details !== undefined && restoreAllowed(details);
}

export async function promptRestore(target: OffloadTarget, followUp = false): Promise<boolean> {
    const details = await detailsOf(target);
    if (details === undefined) return true;
    const answer = await openModal<true, { name: string; details: OffloadedDetails | null; restore: () => Promise<string>; followUp: boolean }>(OffloadPrompt, {
        name: target.label || t('offload.prompt.name_fallback'),
        details,
        restore: () => restoreSentence(target),
        followUp,
    });
    return answer === true;
}

export async function runWithOffloadRestore<T>(target: OffloadTarget, action: () => Promise<T>): Promise<T | typeof CANCELLED> {
    let refused: unknown;
    try {
        const out = await action();
        if (!isOffloadedAnswer(out)) return out;
        refused = out;
    } catch (err) {
        if (!isOffloadedError(err)) throw err;
        refused = err;
    }
    const named: OffloadTarget = { ...target, sessionUuid: target.sessionUuid || sessionUuidOf(refused) };
    if (!named.sessionUuid && !named.conversationId) {
        if (refused instanceof Error) throw refused;
        return refused as T;
    }
    if (!(await promptRestore(named, true))) return CANCELLED;
    return await action();
}

function sessionUuidOf(refusal: unknown): string | null {
    const bag = refusal as { session_uuid?: unknown; body?: { session_uuid?: unknown } } | null;
    const found = bag?.session_uuid ?? bag?.body?.session_uuid;
    return typeof found === 'string' && found ? found : null;
}
