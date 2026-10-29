
export const SUBMIT_KEYS = {
    submitAction: 'skill.submit.action',
    submitTitle: 'skill.submit.title',
    submitLead: 'skill.submit.lead',
    submitFolderLabel: 'skill.submit.folder.label',
    submitFolderPlaceholder: 'skill.submit.folder.placeholder',
    submitFolderBrowse: 'skill.submit.folder.browse',
    submitPickerAbsent: 'skill.submit.folder.picker_absent',
    /* could not be read */
    submitPartial: 'skill.submit.partial',
    submitIdle: 'skill.submit.idle',
    submitReading: 'skill.submit.reading',
    /* could not be read */
    submitUnavailable: 'skill.submit.unavailable',
    submitFilesHeading: 'skill.submit.files.heading',
    submitFilesCount: 'skill.submit.files.count',
    submitFilesMore: 'skill.submit.files.more',
    submitName: 'skill.submit.name',
    submitVersion: 'skill.submit.version',
    submitRefusalsHeading: 'skill.submit.refusals.heading',
    submitConfirm: 'skill.submit.confirm',
    submitCancel: 'skill.submit.cancel',
    submitSignedOut: 'skill.submit.signed_out',
};

export const SUBMIT_REFUSAL_CODES = new Set([
    'submission_invalid',
    'name_reserved',
    'scripts_not_supported',
    'plugin_not_safe',
    'skill_not_safe',
    'kind_mismatch',
    'name_taken',
    'name_pending',
    'body_too_large',
    'rate_limited',
    'unauthorized',
    'unavailable',
]);

export function submitRefusalKey(code) {
    const trimmed = typeof code === 'string' ? code.trim() : '';
    if (!trimmed) return 'skill.submit.refused.unknown';
    if (!SUBMIT_REFUSAL_CODES.has(trimmed)) return 'skill.submit.refused.unrecognised';
    return 'skill.submit.refused.' + trimmed;
}

export function submitRefusalMessage(code, detail, t) {
    const key = submitRefusalKey(code);
    return t(key, { code: typeof code === 'string' ? code : '', detail: detail || '' });
}
