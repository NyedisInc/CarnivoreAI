
export const HOME_KEYS = {
    errorDismiss: 'home.error.dismiss',
    statusConnecting: 'home.status.connecting',
    statusDetaching: 'home.status.detaching',
    statusOpening: 'home.status.opening',
    connectFailed: 'home.nav.connect_failed',
    detachFailed: 'home.nav.detach_failed',
    openFailed: 'home.nav.open_failed',
    attachFailed: 'home.nav.attach_failed',
    returnFailed: 'home.nav.return_failed',
    sessionNotFound: 'home.nav.session_not_found',
    deepLinkRefusesCreate: 'home.nav.deeplink_refuses_create',
    refusedFallbackName: 'home.project.refused.fallback_name',
    refusedFallbackPath: 'home.project.refused.fallback_path',
    refusedMissing: 'home.project.refused.missing',
    refusedUnreachable: 'home.project.refused.unreachable',
    refusedUnreachableDetail: 'home.project.refused.unreachable_detail',
    refusedUnknown: 'home.project.refused.unknown',
};


export function refusedProjectNotice(data, t) {
    const d = data || {};
    const name = d.name || t(HOME_KEYS.refusedFallbackName);
    const path = d.path || t(HOME_KEYS.refusedFallbackPath);
    const presence = d.presence || 'unchecked';
    if (presence === 'missing') {
        return { rung: 'missing', text: t(HOME_KEYS.refusedMissing, { name, path }) };
    }
    if (presence === 'unreachable') {
        const detail = d.detail || t(HOME_KEYS.refusedUnreachableDetail);
        return {
            rung: 'unreachable',
            text: t(HOME_KEYS.refusedUnreachable, { name, path, detail }),
        };
    }
    return {
        rung: 'unknown',
        text: t(HOME_KEYS.refusedUnknown, { name, path, state: presence }),
    };
}

export function failureReason(error, t) {
    if (error && typeof error === 'object' && typeof error.message === 'string' && error.message) {
        return error.message;
    }
    const text = error == null ? '' : String(error);
    return text || t('error.server_unreachable');
}
