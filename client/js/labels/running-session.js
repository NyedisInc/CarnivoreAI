
export const RUNNING_SESSION_KEYS = {
    attentionHead: 'session.listing.attention.head',
    attentionTitle: 'session.listing.attention.title',
    attentionDetail: 'session.listing.attention.detail',
    attentionSourcesUnknown: 'session.listing.attention.sources.unknown',
    attentionNote: 'session.listing.attention.note',
    count: 'session.running.count',
    countUnavailable: 'session.running.count.unavailable',
    rowIdTitle: 'session.row_id.title',
    ageSeconds: 'session.age.seconds',
    ageMinutes: 'session.age.minutes',
    ageHours: 'session.age.hours',
    ageDays: 'session.age.days',
    ageUnknown: 'session.age.unknown',
    renameAction: 'session.rename.action',
    renameUnopened: 'session.rename.unavailable.unopened',
    renameUnadopted: 'session.rename.unavailable.unadopted',
    renameUnknownOwner: 'session.rename.unavailable.unknown_owner',
    renameInputAria: 'session.rename.input.aria',
    renameFailed: 'session.rename.failed',
    renameFailedInUse: 'session.rename.failed.in_use',
    renameFailedInvalid: 'session.rename.failed.invalid',
    renameFailedMissing: 'session.rename.failed.missing',
    renameRuleUnavailable: 'session.rename.rule_unavailable',
    forkAction: 'session.fork.action',
    forkAria: 'session.fork.action.aria',
    forkTitle: 'session.fork.action.title',
    actionClose: 'session.action.close',
    actionRemove: 'session.action.remove',
    actionRestart: 'session.action.restart',
    actionFailed: 'session.action.failed',
    themeSwatch: 'session.theme.swatch',
    wrapperTitle: 'session.wrapper.title',
    badgeTmux: 'session.badge.tmux',
    badgeExternal: 'session.badge.external',
    respawnNoPicker: 'session.respawn.no_picker',
    respawnUnpredictable: 'session.respawn.unpredictable',
    respawnFailed: 'session.respawn.failed',
    respawnNoReason: 'session.respawn.failed.no_reason',
    respawnChoiceUnsaved: 'session.respawn.choice_unsaved',
    respawnNoReopen: 'session.respawn.no_reopen',
    attachFailed: 'session.attach.failed',
    serverUnreachable: 'error.server_unreachable',
    apiUnavailable: 'session.api.unavailable',
};

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

export function runningCountLabel(count, t) {
    return t(RUNNING_SESSION_KEYS.count, { count: count });
}

/* could not be determined */
export function runningCountUnavailableLabel(t) {
    return t(RUNNING_SESSION_KEYS.countUnavailable);
}

/* could not be reached */
export function listingAttentionDetail(listing, t) {
    const state = listing || {};
    const detail = state.detail || t(RUNNING_SESSION_KEYS.serverUnreachable);
    const sources = (state.sources && state.sources.length)
        ? state.sources.join(' + ')
        : t(RUNNING_SESSION_KEYS.attentionSourcesUnknown);
    return t(RUNNING_SESSION_KEYS.attentionDetail, {
        detail: detail,
        sources: sources,
        reason: state.reason || 'probe_error',
    });
}

export function relativeAge(epochSeconds, t, nowMs) {
    if (!epochSeconds || typeof epochSeconds !== 'number') {
        return t(RUNNING_SESSION_KEYS.ageUnknown);
    }
    const now = typeof nowMs === 'number' ? nowMs : Date.now();
    const delta = Math.max(0, Math.floor(now / 1000) - epochSeconds);
    if (delta < MINUTE) {
        return t(RUNNING_SESSION_KEYS.ageSeconds, { count: delta });
    }
    if (delta < HOUR) {
        return t(RUNNING_SESSION_KEYS.ageMinutes, {
            count: Math.floor(delta / MINUTE),
        });
    }
    if (delta < DAY) {
        return t(RUNNING_SESSION_KEYS.ageHours, {
            count: Math.floor(delta / HOUR),
        });
    }
    return t(RUNNING_SESSION_KEYS.ageDays, { count: Math.floor(delta / DAY) });
}

export function rowActionFailed(actionLabel, reason, t) {
    return t(RUNNING_SESSION_KEYS.actionFailed, {
        action: actionLabel,
        reason: reason,
    });
}
