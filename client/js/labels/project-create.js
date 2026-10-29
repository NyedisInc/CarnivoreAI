
export const PROJECT_CREATE_KEYS = {
    nameRequired: 'project.name.refused.required',
    nameIllegalChar: 'project.name.refused.illegal_char',
    nameIllegalNull: 'project.name.refused.illegal_null',
    nameControlChars: 'project.name.refused.control_chars',
    nameReserved: 'project.name.refused.reserved',
    nameLeadingDot: 'project.name.refused.leading_dot',
    nameTooLong: 'project.name.refused.too_long',
    nameTitle: 'project.name.modal.title',
    nameTitleForAgent: 'project.name.modal.title_for_agent',
    nameAddTitle: 'project.name.modal.title_add',
    nameLabel: 'project.name.modal.name_label',
    namePlaceholder: 'project.name.modal.name_placeholder',
    nameHint: 'project.name.modal.name_hint',
    descriptionLabel: 'project.name.modal.description_label',
    descriptionPlaceholder: 'project.name.modal.description_placeholder',
    descriptionHint: 'project.name.modal.description_hint',
    folderLabel: 'project.name.modal.folder_label',
    confirmCreate: 'project.name.modal.confirm_create',
    wizardNext: 'project.wizard.next',
    wizardCreate: 'project.wizard.create',
    folderRemoteHint: 'project.folder.modal.remote_hint',
    folderSshHint: 'project.folder.modal.ssh_hint',
    remoteBrowseOld: 'project.folder.modal.remote_browse_old',
    remoteBrowseUnreachable: 'project.folder.modal.remote_browse_unreachable',
    remoteBrowseRefused: 'project.folder.modal.remote_browse_refused',
    remotePickerTitle: 'project.folder.picker.remote_title',
    remotePickerNotFound: 'project.folder.picker.remote_not_found',
    remotePickerOutside: 'project.folder.picker.remote_outside',
    remotePickerUnreadable: 'project.folder.picker.remote_unreadable',
    remotePickerInvalid: 'project.folder.picker.remote_invalid',
    remotePickerTruncated: 'project.folder.picker.remote_truncated',
    confirmOpen: 'project.name.modal.confirm_open',
    cancel: 'project.modal.cancel',
    folderTitle: 'project.folder.modal.title',
    folderParentLabel: 'project.folder.modal.parent_label',
    folderParentHint: 'project.folder.modal.parent_hint',
    folderParentLoading: 'project.folder.modal.parent_loading',
    folderParentUnavailable: 'project.folder.modal.parent_unavailable',
    folderNoPath: 'project.folder.modal.no_path',
    folderChoosePrompt: 'project.folder.modal.choose_prompt',
    folderPickerUnavailable: 'project.folder.modal.picker_unavailable',
    folderBrowse: 'project.folder.modal.browse',
    choiceDefaultTitle: 'project.choice.default_title',
    choiceHint: 'project.choice.hint',
    choiceEmptyHint: 'project.choice.empty_hint',
    choiceEmptyFallback: 'project.choice.empty_fallback',
    choiceOk: 'project.choice.ok',
    hostTitle: 'project.host.modal.title',
    hostNotProbed: 'project.host.modal.not_probed',
    hostPeerOffline: 'project.host.modal.peer_offline',
    hostPeerRefuses: 'project.host.modal.peer_refuses',
    newProjectTitle: 'project.new.title',
    newProjectEmpty: 'project.new.empty',
    newProjectEmptySub: 'project.new.empty.sub',
    newProjectClone: 'project.new.clone',
    newProjectCloneSub: 'project.new.clone.sub',
    newProjectFolder: 'project.new.folder',
    newProjectFolderSub: 'project.new.folder.sub',
    newSessionTitle: 'project.session.title',
    newSessionPickTitle: 'project.session.pick_title',
    newSessionCannotDetermine: 'project.session.cannot_determine',
    newSessionNone: 'project.session.none',
    editTitle: 'project.edit.modal.title',
    editFolderHint: 'project.edit.modal.folder_hint',
    editSave: 'project.edit.modal.save',
    editStatusUpdating: 'project.edit.status.updating',
    editStatusDone: 'project.edit.status.done',
    editFailed: 'project.edit.failed',
    archiveTitle: 'project.archive.confirm.title',
    archiveMessage: 'project.archive.confirm.message',
    archiveDetails: 'project.archive.confirm.details',
    archiveConfirm: 'project.archive.confirm.primary',
    archiveFailed: 'project.archive.failed',
    restoreFailed: 'project.restore.failed',
    cloneTitle: 'project.clone.modal.title',
    cloneUrlLabel: 'project.clone.modal.url_label',
    cloneUrlPlaceholder: 'project.clone.modal.url_placeholder',
    cloneUrlHint: 'project.clone.modal.url_hint',
    cloneParentLabel: 'project.clone.modal.parent_label',
    cloneParentHint: 'project.clone.modal.parent_hint',
    cloneDescriptionPlaceholder: 'project.clone.modal.description_placeholder',
    cloneConfirm: 'project.clone.modal.confirm',
    cloneBusy: 'project.clone.status.busy',
    cloneNeedsUrl: 'project.clone.status.needs_url',
    cloneAuth: 'project.clone.error.auth',
    cloneNotFound: 'project.clone.error.not_found',
    cloneExists: 'project.clone.error.exists',
    cloneNoGh: 'project.clone.error.no_gh',
    cloneTimeout: 'project.clone.error.timeout',
    cloneFailed: 'project.clone.error.failed',
    createStatus: 'project.create.status',
    createStatusForAgent: 'project.create.status_for_agent',
    createConsoleStatus: 'project.create.console.status',
    createFailed: 'project.create.failed',
    rootRefused: 'project.create.root_refused',
    createFolderFailed: 'project.create.folder_failed',
    uniqueNameFailed: 'project.create.unique_name_failed',
};

const REFUSAL_KEY_BY_CODE = {
    required: PROJECT_CREATE_KEYS.nameRequired,
    illegal_char: PROJECT_CREATE_KEYS.nameIllegalChar,
    illegal_null: PROJECT_CREATE_KEYS.nameIllegalNull,
    control_chars: PROJECT_CREATE_KEYS.nameControlChars,
    reserved: PROJECT_CREATE_KEYS.nameReserved,
    leading_dot: PROJECT_CREATE_KEYS.nameLeadingDot,
    too_long: PROJECT_CREATE_KEYS.nameTooLong,
};

export function nameRefusal(verdict, t) {
    if (!verdict || verdict.ok) return null;
    const key = REFUSAL_KEY_BY_CODE[verdict.code] || PROJECT_CREATE_KEYS.nameRequired;
    return t(key, verdict.params || {});
}

export function uniqueNameFailure(error, t) {
    const key = error && error.cloudeKey;
    if (key) return t(key);
    const message = error && error.message;
    return message || t(PROJECT_CREATE_KEYS.uniqueNameFailed);
}

export function cloneFailure(error, t) {
    const msg = error instanceof Error ? error.message : String(error ?? '');
    const lower = msg.toLowerCase();
    if (lower.includes('not authenticated') || lower.includes('auth/network')
        || lower.includes('gh auth login')) {
        return t(PROJECT_CREATE_KEYS.cloneAuth);
    }
    if (lower.includes('repository not found') || lower.includes('repo not found')
        || lower.startsWith('not found')) {
        return t(PROJECT_CREATE_KEYS.cloneNotFound);
    }
    if (lower.includes('already exists')) {
        return t(PROJECT_CREATE_KEYS.cloneExists);
    }
    if (lower.includes('gh cli not') || lower.includes('install with `brew install gh`')) {
        return t(PROJECT_CREATE_KEYS.cloneNoGh);
    }
    if (lower.includes('timed out') || lower.includes('timeout')) {
        return t(PROJECT_CREATE_KEYS.cloneTimeout);
    }
    const cleaned = msg.replace(/^HTTP\s+\d{3}:?\s*/i, '').trim();
    return cleaned || t(PROJECT_CREATE_KEYS.cloneFailed);
}
