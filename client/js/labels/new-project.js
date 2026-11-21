
export const NEW_PROJECT_KEYS = {
    title: 'newproject.title',
    nameLabel: 'newproject.name.label',
    namePlaceholder: 'newproject.name.placeholder',
    companyLabel: 'newproject.company.label',
    companyParentItself: 'newproject.company.parent_itself',
    companyNew: 'newproject.company.new',
    companyChoose: 'newproject.company.choose',
    companyNoneYet: 'newproject.company.none_yet',
    companyFailed: 'newproject.company.failed',
    newcoTitle: 'newproject.newco.title',
    newcoName: 'newproject.newco.name',
    newcoParent: 'newproject.newco.parent',
    newcoParentNone: 'newproject.newco.parent_none',
    newcoFolder: 'newproject.newco.folder',
    newcoFolderPlaceholder: 'newproject.newco.folder_placeholder',
    newcoFolderHelp: 'newproject.newco.folder_help',
    newcoFolderHelpBlank: 'newproject.newco.folder_help_blank',
    newcoOutside: 'newproject.newco.outside',
    newcoCancel: 'newproject.newco.cancel',
    newcoCreate: 'newproject.newco.create',
    newcoFailed: 'newproject.newco.failed',
    findLabel: 'newproject.find.label',
    findPlaceholder: 'newproject.find.placeholder',
    treeLabel: 'newproject.tree.label',
    treeLoading: 'newproject.tree.loading',
    treeEmpty: 'newproject.tree.empty',
    treeFailed: 'newproject.tree.failed',
    treeTruncated: 'newproject.tree.truncated',
    treeTagProject: 'newproject.tree.tag_project',
    pathLabel: 'newproject.path.label',
    pathNone: 'newproject.path.none',
    landsLabel: 'newproject.lands.label',
    landsFailed: 'newproject.lands.failed',
    landsNewCompany: 'newproject.lands.new_company',
    landsName: 'newproject.lands.name',
    landsNameMissing: 'newproject.lands.name_missing',
    confirm: 'newproject.confirm',
    cancel: 'newproject.cancel',
};

const FINDING_KEYS = {
    pick_folder: 'newproject.lands.pick_folder',
    scratch: 'newproject.lands.scratch',
    sign_in_folder: 'newproject.lands.sign_in_folder',
    already_project: 'newproject.lands.already_project',
    inside_project: 'newproject.lands.inside_project',
    outside_org: 'newproject.lands.outside_org',
    no_company: 'newproject.lands.no_company',
    company: 'newproject.lands.company',
    other_company: 'newproject.lands.other_company',
    clean: 'newproject.lands.clean',
    new_company: 'newproject.lands.new_company',
    name: 'newproject.lands.name',
    name_missing: 'newproject.lands.name_missing',
};

const LEVEL_KEYS = {
    ok: 'newproject.lands.level_ok',
    warn: 'newproject.lands.level_warn',
    block: 'newproject.lands.level_block',
};

export function landsLine(finding, t) {
    const key = FINDING_KEYS[finding.code];
    return {
        level: finding.level,
        word: t(LEVEL_KEYS[finding.level] || LEVEL_KEYS.warn),
        text: key ? t(key, finding.params || {}) : finding.code,
    };
}
