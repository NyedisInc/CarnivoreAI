/* could not be read */

export const PROJECT_TREE_KEYS = {
    emptyTitle: 'project.list.empty',
    emptyHint: 'project.list.empty.hint',
    noProject: 'project.tree.no_project',
    sessionCount: 'project.tree.session_count',
    attentionHead: 'project.tree.attention.head',
    attentionTitle: 'project.tree.attention.title',
    toggleAria: 'project.node.toggle.aria',
    archivedCount: 'project.archived.notice.count',
    archivedUnknown: 'project.archived.notice.unknown',
    authorityUnknown: 'project.authority.unknown',
    presenceMissing: 'project.presence.missing',
    presenceUnreachable: 'project.presence.unreachable',
    presenceUnreachableDetailUnknown: 'project.presence.unreachable.detail_unknown',
    badgeArchived: 'project.badge.archived',
    actionEdit: 'project.action.edit',
    actionArchiveTitle: 'project.action.archive.title',
    actionArchiveAria: 'project.action.archive.aria',
    actionRestoreTitle: 'project.action.restore.title',
    actionRestoreAria: 'project.action.restore.aria',
    archivedShow: 'project.archived.show',
    archivedHide: 'project.archived.hide',
    projectWorkUnrecorded: 'project.work.unrecorded',
    sessionWorkUnrecorded: 'session.work.unrecorded',
    badgeTmux: 'session.badge.tmux',
    badgeExternal: 'session.badge.external',
    badgeEnded: 'session.badge.ended',
    familyUnknown: 'session.agent.family.unknown',
};

export function sessionCountLabel(count, t) {
    return t(PROJECT_TREE_KEYS.sessionCount, { count: count });
}

export function attentionTitle(count, t) {
    return t(PROJECT_TREE_KEYS.attentionTitle, { count: count });
}

export function attentionReason(item, t) {
    if (!item) return '';
    const detail = item.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    return t(item.reasonKey);
}

export function archivedNoticeText(notice, t) {
    if (!notice) return null;
    if (notice.kind === 'count') {
        return t(PROJECT_TREE_KEYS.archivedCount, { count: notice.count });
    }
    if (notice.kind === 'unknown') return t(PROJECT_TREE_KEYS.archivedUnknown);
    return null;
}

export function authorityBannerText(banner, t) {
    if (!banner) return null;
    if (banner.kind === 'unknown') return t(PROJECT_TREE_KEYS.authorityUnknown);
    if (banner.kind === 'degraded') return banner.message || '';
    return null;
}

export function presenceBadgeText(state, detail, t) {
    if (state === 'missing') return t(PROJECT_TREE_KEYS.presenceMissing);
    if (state === 'unreachable') {
        const reason = (typeof detail === 'string' && detail.trim())
            ? detail
            : t(PROJECT_TREE_KEYS.presenceUnreachableDetailUnknown);
        return t(PROJECT_TREE_KEYS.presenceUnreachable, { detail: reason });
    }
    return null;
}

export function workTitle(work, t) {
    if (!work || !work.titleKey) return null;
    return t(work.titleKey);
}
