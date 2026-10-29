import { publishRefusalKey } from '../../../../client/js/labels/skill-publish.js';
import { clipChars } from '../catalog/bounds';
import { errorText } from '../catalog/publish';
import type { Translate } from '../sessions/types';
import type { ActionName, Source } from './types';

const KEYS: Record<Source | ActionName, string> = {
    account: 'skill.publish.handle.failed',
    mine: 'skill.publish.submissions.failed',
    folders: 'publish.page.failure.folders',
    limits: 'publish.page.failure.limits',
    rules: 'publish.page.failure.rules',
    facts: 'publish.page.failure.facts',
    report: 'skill.publish.report.failed',
    check: 'skill.publish.preflight.failed',
    send: 'skill.publish.send_failed',
    media: 'skill.publish.send_failed',
    appeal: 'publish.page.failure.appeal',
    withdraw: 'publish.page.failure.withdraw',
    register: 'skill.publish.register.failed',
};

const UNRECOGNISED = 'skill.submit.refused.unrecognised';

export function isUnmappedCode(code: string): boolean {
    return publishRefusalKey(code) === UNRECOGNISED;
}

function statusOf(error: unknown): number {
    const status = (error as { status?: unknown } | null)?.status;
    return typeof status === 'number' ? status : 0;
}

export function codeOf(error: unknown): string {
    const code = (error as { detail?: { code?: unknown } } | null)?.detail?.code;
    return typeof code === 'string' ? code : '';
}

export function detailOf(error: unknown): string {
    const detail = (error as { detail?: { detail?: unknown } } | null)?.detail?.detail;
    return typeof detail === 'string' ? clipChars(detail, 300) ?? '' : '';
}

/* could not be reached */
function isTransport(error: unknown): boolean {
    const e = error as { name?: unknown; code?: unknown } | null;
    return statusOf(error) === 0 && (e?.name === 'TypeError' || e?.code === 'unreachable' || codeOf(error) === 'unreachable');
}

function anyCode(error: unknown): string {
    const code = (error as { code?: unknown } | null)?.code;
    return codeOf(error) || (typeof code === 'string' ? code : '');
}

function plainLine(source: Source | ActionName, error: unknown, t: Translate): string | null {
    const status = statusOf(error);
    if (isTransport(error) || status === 502 || status === 503 || status === 504) return t('publish.page.failure.offline');
    const code = anyCode(error);
    if (source === 'withdraw' && code === 'not_withdrawable') return t('publish.page.failure.not_withdrawable');
    if (source === 'appeal' && (code === 'appeal_limit' || code === 'not_rejected')) return t(`publish.page.failure.${code}`);
    if (status >= 500) return t(source === 'folders' ? 'publish.page.failure.folders_server' : 'publish.page.failure.server');
    if (source === 'mine' || source === 'limits') {
        if (status === 429) return t('publish.page.failure.mine_rate_limited');
        if (status === 403 || status === 401) return t('publish.page.failure.session_expired');
    }
    if (code && isUnmappedCode(code)) return detailOf(error) || t('publish.page.failure.generic');
    const message = (error as { message?: unknown } | null)?.message;
    if (!code && status > 0 && message === t('opscenter.auth.server_answered', { status })) return t('publish.page.failure.generic');
    return null;
}

export function failureLine(source: Source | ActionName, error: unknown, t: Translate): string {
    return plainLine(source, error, t) ?? t(KEYS[source], { reason: errorText(error, t) });
}

export function failureReason(source: Source | ActionName, error: unknown, t: Translate): string {
    return plainLine(source, error, t) === null ? errorText(error, t) : '';
}
