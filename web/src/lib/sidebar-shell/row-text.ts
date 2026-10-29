import { t } from '../i18n/index.svelte';
import { labelWithSource } from '../status-dot';
import type { SidebarRow } from './legacy';
import type { RowHost } from './row-host';

export type RenameState = 'renameable' | 'unavailable' | 'unknown';

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

export function renameState(r: SidebarRow, host: RowHost): { state: RenameState; reason: string } {
    if (r.asleep && r.session_uuid && !r.archived) return { state: 'renameable', reason: 'rename from the session menu or F2' };
    if (r.asleep) {
        return { state: 'unavailable', reason: t('session.asleep.hint') };
    }
    if (r.session_id) return { state: 'renameable', reason: 'rename from the session menu or F2' };
    if (r.created_by_cloude == null) {
        return {
            state: 'unknown',
            reason: 'cannot rename: CANNOT DETERMINE whether this session is yours,'
                + ' so whether it can be renamed is unknown',
        };
    }
    return {
        state: 'unavailable',
        reason: r.created_by_cloude
            ? 'cannot rename until this session is open - click the row to open it'
            : 'cannot rename until this session is adopted - click the row to adopt it',
    };
}

export function ageLabel(epoch: unknown, suffix = ''): string {
    if (!epoch || typeof epoch !== 'number') return '';
    const secs = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
    let out: string;
    if (secs < MINUTE) out = `${secs}s`;
    else if (secs < HOUR) out = `${Math.floor(secs / MINUTE)}m`;
    else if (secs < DAY) out = `${Math.floor(secs / HOUR)}h`;
    else out = `${Math.floor(secs / DAY)}d`;
    return out + suffix;
}

export function epochFromIso(value: unknown): number | null {
    if (!value || typeof value !== 'string') return null;
    const ms = Date.parse(value);
    return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

export function whenLabel(r: SidebarRow): string {
    const epoch = epochFromIso(r.last_work_at);
    return epoch === null ? '' : ageLabel(epoch, ' ago');
}

export function originBadge(r: SidebarRow, full: boolean): { text: string; title: string | null } | null {
    const own = r.created_by_cloude;
    if (own == null) return { text: 'unknown', title: 'CANNOT DETERMINE whether this session is ours' };
    if (own === true) return full ? { text: 'tmux', title: null } : null;
    return { text: 'external', title: null };
}

export function hintText(r: SidebarRow): string {
    if (!r.activity_hint) return '';
    const bare = labelWithSource(r.status, r.status_source, null);
    const withHint = labelWithSource(r.status, r.status_source, r.activity_hint);
    const prefix = `${bare}, `;
    return withHint.indexOf(prefix) === 0 ? withHint.slice(prefix.length) : '';
}

export function workAttrs(r: SidebarRow): Record<string, string> {
    if (r.last_work_at) {
        return {
            'data-work': 'recorded',
            'data-work-at': String(r.last_work_at).replace(/[^0-9TZ:.+-]/g, ''),
        };
    }
    return { 'data-work': 'unrecorded' };
}
