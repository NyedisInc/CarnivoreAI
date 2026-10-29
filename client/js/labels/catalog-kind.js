/* the reading pane */

export const CATALOG_KINDS = new Set(['skill', 'theme', 'plugin', 'loadout', 'mod', 'cplug']);

export const KIND_KEYS = {
    kindSkill: 'catalog.kind.skill',
    kindTheme: 'catalog.kind.theme',
    kindPlugin: 'catalog.kind.plugin',
    kindLoadout: 'catalog.kind.loadout',
    kindMod: 'catalog.kind.mod',
    kindCplug: 'catalog.kind.cplug',
    kindFilterLegend: 'catalog.kind.filter.legend',
    kindFilterAny: 'catalog.kind.filter.any',
    themeBodyHeading: 'theme.sheet.body.heading',
    themeEffectsHeading: 'theme.sheet.effects.heading',
    themeEffectsDetail: 'theme.sheet.effects.detail',
    themeEffectsFile: 'theme.sheet.effects.file',
    themeScopeGlobalOnly: 'theme.sheet.scope.global_only',
    pluginBodyHeading: 'plugin.sheet.body.heading',
    pluginPartsHeading: 'plugin.sheet.parts.heading',
    pluginPartsAbsent: 'plugin.sheet.parts.absent',
    pluginPartCount: 'plugin.sheet.parts.count',
    pluginMcpHeading: 'plugin.sheet.mcp.heading',
    pluginMcpLead: 'plugin.sheet.mcp.lead',
    pluginMcpEnv: 'plugin.sheet.mcp.env',
    pluginScopeNote: 'plugin.sheet.scope.note',
    pluginScopeProjectTrust: 'plugin.sheet.scope.project_trust',
    loadoutBodyHeading: 'loadout.sheet.body.heading',
    loadoutMembersHeading: 'loadout.sheet.members.heading',
    loadoutMembersAbsent: 'loadout.sheet.members.absent',
    loadoutMemberLine: 'loadout.sheet.member.line',
    loadoutMemberInstalled: 'loadout.sheet.member.installed',
    loadoutMemberScripts: 'loadout.sheet.member.scripts',
    loadoutMemberInstructions: 'loadout.sheet.member.instructions',
    loadoutThemeNote: 'loadout.sheet.theme.note',
    loadoutScopeGlobalOnly: 'loadout.sheet.scope.global_only',
    loadoutPartialHeading: 'loadout.partial.heading',
    loadoutPartialDetail: 'loadout.partial.detail',
    modBodyHeading: 'mods.sheet.body.heading',
    modScopeGlobalOnly: 'mods.sheet.scope.global_only',
    modTrust: 'mods.consent.trust',
    modCallsNote: 'mods.consent.calls_note',
    modHooks: 'mods.consent.hooks',
    modCalls: 'mods.consent.calls',
    modSpendsUsage: 'mods.consent.spends_usage',
    modGating: 'mods.consent.gating',
    modNoCatch: 'mods.consent.no_catch',
    modNotesRaw: 'mods.consent.notes_raw',
    modNoReport: 'mods.consent.no_report',
    modVersion: 'mods.consent.version',
    modNewSessions: 'mods.consent.new_sessions',
    modWhere: 'mods.consent.where',
    modTickTrust: 'mods.consent.tick_trust',
    modTickFlagged: 'mods.consent.tick_flagged',
    cplugScopeGlobalOnly: 'cplugs.sheet.scope.global_only',
    cplugTrust: 'cplugs.consent.trust',
    cplugNoFacts: 'cplugs.consent.no_facts',
    cplugContains: 'cplugs.consent.contains',
    cplugPermissions: 'cplugs.consent.permissions',
    cplugNoPermissions: 'cplugs.consent.no_permissions',
    cplugTools: 'cplugs.consent.tools',
    cplugNoTools: 'cplugs.consent.no_tools',
    cplugHosts: 'cplugs.consent.hosts',
    cplugSecrets: 'cplugs.consent.secrets',
    cplugSentTo: 'cplugs.consent.sent_to',
    cplugNotEnabled: 'cplugs.consent.not_enabled',
    cplugTick: 'cplugs.consent.tick',
};

export const PLUGIN_PART_KEYS = {
    'skills/': 'plugin.part.skills',
    'commands/': 'plugin.part.commands',
    'agents/': 'plugin.part.agents',
    'hooks/': 'plugin.part.hooks',
    'workflows/': 'plugin.part.workflows',
    'output-styles/': 'plugin.part.output_styles',
    'themes/': 'plugin.part.themes',
    'monitors/': 'plugin.part.monitors',
    'bin/': 'plugin.part.bin',
    '.mcp.json': 'plugin.part.mcp',
    '.lsp.json': 'plugin.part.lsp',
    'settings.json': 'plugin.part.settings',
};

export function kindKey(kind) {
    const trimmed = typeof kind === 'string' ? kind.trim() : '';
    if (!CATALOG_KINDS.has(trimmed)) return null;
    return 'catalog.kind.' + trimmed;
}

export function kindLabel(kind, t) {
    const key = kindKey(kind);
    return key ? t(key) : null;
}

export function bodyHeadingKey(kind) {
    const trimmed = typeof kind === 'string' ? kind.trim() : '';
    if (trimmed === 'theme') return KIND_KEYS.themeBodyHeading;
    if (trimmed === 'plugin') return KIND_KEYS.pluginBodyHeading;
    if (trimmed === 'loadout') return KIND_KEYS.loadoutBodyHeading;
    if (trimmed === 'mod') return KIND_KEYS.modBodyHeading;
    return 'skill.sheet.body.heading';
}
