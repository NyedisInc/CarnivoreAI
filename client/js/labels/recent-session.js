
import { reasonOf } from './error-reason.js';

export const RECENT_KEYS = {
    count: 'session.recent.count',
    countUnavailable: 'session.recent.count.unavailable',
    unavailableTitle: 'session.recent.unavailable.title',
    unavailableDetail: 'session.recent.unavailable.detail',
    loadFailed: 'session.recent.load_failed',
    emptyIncludingArchived: 'session.recent.empty_including_archived',
    lifecycleEnded: 'session.recent.lifecycle.ended',
    closedLabel: 'session.recent.closed.label',
    closedTitle: 'session.recent.closed.title',
    lastActiveLabel: 'session.recent.last_active.label',
    lastActiveTitle: 'session.recent.last_active.title',
    addedLabel: 'session.recent.added.label',
    addedTitle: 'session.recent.added.title',
    ageNow: 'session.recent.age.now',
    ageMinutes: 'session.recent.age.minutes',
    ageHours: 'session.recent.age.hours',
    ageDays: 'session.recent.age.days',
    nameFallback: 'session.name.fallback',
    archiveAction: 'session.archive.action',
    archiveActionTitle: 'session.archive.action.title',
    archiveActionAria: 'session.archive.action.aria',
    archiveBadge: 'session.archive.badge',
    archiveBadgeTitle: 'session.archive.badge.title',
    archiveShow: 'session.archive.show',
    archiveHide: 'session.archive.hide',
    archiveFailedNoId: 'session.archive.failed.no_id',
    archiveFailed: 'session.archive.failed',
    restartAction: 'session.restart.action',
    restartFailed: 'session.restart.failed',
    restartPending: 'session.restart.pending',
    restartRowFailed: 'session.restart.row_failed',
    restartUnidentified: 'session.restart.unidentified',
    restartUnidentifiedNamed: 'session.restart.unidentified.named',
    restartUnsaid: 'session.restart.unsaid',
    restartNoneRecorded: 'session.restart.none_recorded',
    restartNoneRecordedNamed: 'session.restart.none_recorded.named',
    restartUnknown: 'session.restart.unknown',
    restartUnknownNamed: 'session.restart.unknown.named',
    restartRowNotReused: 'session.restart.row_not_reused',
    restartRowNotReusedNamed: 'session.restart.row_not_reused.named',
    forkFailedNoName: 'session.fork.failed.no_name',
    forkFailedNoConversation: 'session.fork.failed.no_conversation',
    forkFailed: 'session.fork.failed',
    forkLineageUnrecorded: 'session.fork.lineage_unrecorded',
    serverUnreachable: 'error.server_unreachable',
};

function pickNamed(plainKey, namedKey, title, t) {
    const trimmed = typeof title === 'string' ? title.trim() : '';
    return trimmed ? t(namedKey, { title: trimmed }) : t(plainKey);
}

export function recentCountLabel(count, t) {
    return t(RECENT_KEYS.count, { count });
}

export function recentCountUnavailableLabel(t) {
    return t(RECENT_KEYS.countUnavailable);
}

export function unavailableDetail(notice, t) {
    const trimmed = typeof notice === 'string' ? notice.trim() : '';
    return trimmed || t(RECENT_KEYS.unavailableDetail);
}

export function loadFailedNotice(error, t) {
    return t(RECENT_KEYS.loadFailed, { reason: reasonOf(error, t) });
}

/* could not be read */
export function restartNotice(result, t) {
    if (!result) return t(RECENT_KEYS.restartUnsaid);
    const kind = result.conversation;
    const title = result.title_carried;
    if (kind === 'none_recorded') {
        return pickNamed(
            RECENT_KEYS.restartNoneRecorded,
            RECENT_KEYS.restartNoneRecordedNamed,
            title, t,
        );
    }
    if (kind !== 'resumed') {
        return pickNamed(
            RECENT_KEYS.restartUnknown, RECENT_KEYS.restartUnknownNamed, title, t,
        );
    }
    if (result.row_reused === false) {
        const detail = typeof result.detail === 'string' ? result.detail.trim() : '';
        if (detail) return detail;
        return pickNamed(
            RECENT_KEYS.restartRowNotReused,
            RECENT_KEYS.restartRowNotReusedNamed,
            title, t,
        );
    }
    return null;
}

/* could not be determined */
export function unidentifiedRestartNotice(title, t) {
    return pickNamed(
        RECENT_KEYS.restartUnidentified,
        RECENT_KEYS.restartUnidentifiedNamed,
        title, t,
    );
}

export function forkFailureNotice(error, t) {
    const status = error && typeof error === 'object' ? error.status : null;
    if (status === 409) return t(RECENT_KEYS.forkFailedNoConversation);
    return t(RECENT_KEYS.forkFailed, { reason: reasonOf(error, t) });
}
