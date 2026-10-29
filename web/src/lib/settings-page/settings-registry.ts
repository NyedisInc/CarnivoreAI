
import type { AccountFeature } from '../carnivore-account/features';
import { hasDesktopCapability } from './desktop-bridge';

export type SectionId =
    | 'account'
    | 'appearance'
    | 'sessions'
    | 'launch_profiles'
    | 'terminal'
    | 'notifications'
    | 'byoai'
    | 'log_processor'
    | 'remote'
    | 'general'
    | 'desktop'
    | 'keys'
    | 'advanced';

export type ScreenKind = 'launch-profiles' | 'keys' | 'desktop';

export interface SettingsSection {
    readonly id: SectionId;
    readonly icon: string;
    readonly screen?: ScreenKind;
}

export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
    { id: 'account', icon: 'star' },
    { id: 'appearance', icon: 'palette' },
    { id: 'sessions', icon: 'session' },
    { id: 'launch_profiles', icon: 'rocket', screen: 'launch-profiles' },
    { id: 'terminal', icon: 'terminal-glyph' },
    { id: 'notifications', icon: 'bell' },
    { id: 'byoai', icon: 'spark' },
    { id: 'log_processor', icon: 'files' },
    { id: 'remote', icon: 'lock' },
    { id: 'general', icon: 'gear' },
    ...(hasDesktopCapability('desktopState') ? [{ id: 'desktop', icon: 'computer', screen: 'desktop' } as const] : []),
    { id: 'keys', icon: 'keyboard', screen: 'keys' },
    { id: 'advanced', icon: 'cpu' },
];

/* A titled GROUP */
export type GroupId =
    | 'appearance.colors'
    | 'appearance.sidebar'
    | 'appearance.status_bar'
    | 'appearance.control_center'
    | 'appearance.motion'
    | 'sessions.auto_sleep'
    | 'sessions.agents'
    | 'terminal.startup'
    | 'terminal.tui'
    | 'terminal.accessibility'
    | 'terminal.crosstalk_cards'
    | 'notifications.delivery'
    | 'notifications.channels'
    | 'notifications.routing'
    | 'notifications.web_push'
    | 'notifications.messaging'
    | 'byoai.connections'
    | 'byoai.routing'
    | 'byoai.calls'
    | 'log_processor.cplugs'
    | 'account.status'
    | 'account.privacy'
    | 'general.paths'
    | 'general.time'
    | 'general.updates'
    | 'remote.access'
    | 'remote.phone_link'
    | 'remote.api_keys'
    | 'advanced.diagnostics'
    | 'advanced.stats'
    | 'advanced.mcp_tools'
    | 'advanced.beast_mode'
    | 'advanced.developer'
    | 'advanced.migration';

export interface ConfigField {
    readonly group: 'workspace' | 'server_prefs' | 'notifications';
    readonly key: string;
}

export type LinkAction = 'open-wrappers';

export type SettingControl =
    | { readonly kind: 'text'; readonly field: ConfigField; readonly placeholder: string }
    | { readonly kind: 'secret'; readonly field: ConfigField }
    | { readonly kind: 'config-toggle'; readonly field: ConfigField }
    | { readonly kind: 'crosstalk-card'; readonly switch: 'enabled' | 'senderCards' | 'receiverCards' | 'keepCards' }
    | { readonly kind: 'env' }
    | { readonly kind: 'bind' }
    | { readonly kind: 'auto-sleep' }
    | { readonly kind: 'auto-sleep-minutes' }
    | { readonly kind: 'auto-sleep-unread' }
    | { readonly kind: 'auto-sleep-unread-minutes' }
    | { readonly kind: 'animations' }
    | { readonly kind: 'toast-mode' }
    | { readonly kind: 'screen-reader' }
    | { readonly kind: 'time-zone' }
    | { readonly kind: 'row-icons' }
    | { readonly kind: 'theme-picker' }
    | { readonly kind: 'foot-bar-layout'; readonly half: 'collapsed' | 'open' }
    | { readonly kind: 'foot-bar-items' }
    | { readonly kind: 'config-bundle' }
    | { readonly kind: 'web-push' }
    | { readonly kind: 'carnivore-account' }
    | { readonly kind: 'install-report-privacy' }
    | { readonly kind: 'agent-gate' }
    | { readonly kind: 'mcp-server' }
    | { readonly kind: 'phone-link' }
    | { readonly kind: 'api-keys' }
    | { readonly kind: 'tui-cli' }
    | { readonly kind: 'log-level' }
    | { readonly kind: 'app-update' }
    | { readonly kind: 'stats-collection'; readonly part?: 'main' | 'lifecycle' }
    | { readonly kind: 'mcp-tools' }
    | { readonly kind: 'beast-grid' }
    | { readonly kind: 'custom-domain-remove' }
    | { readonly kind: 'notify-destinations' }
    | { readonly kind: 'notify-link' }
    | { readonly kind: 'messaging' }
    | { readonly kind: 'notify-matrix' }
    | { readonly kind: 'notify-mutes' }
    | { readonly kind: 'notify-sync' }
    | { readonly kind: 'ai-connections' }
    | { readonly kind: 'ai-routing' }
    | { readonly kind: 'ai-calls' }
    | { readonly kind: 'pipeline-status' }
    | { readonly kind: 'deepsearch-scope' }
    | { readonly kind: 'link'; readonly action: LinkAction };

export interface SettingDef {
    readonly id: string;
    readonly section: SectionId;
    readonly group: GroupId;
    readonly saves: 'instant' | 'batch' | 'panel';
    readonly control: SettingControl;
    readonly info?: boolean;
    readonly feature?: AccountFeature;
    readonly parent?: string;
    readonly lifecycle?: boolean;
}

const ws = (key: string): ConfigField => ({ group: 'workspace', key });

export const SETTINGS: readonly SettingDef[] = [
    { id: 'carnivore_account', section: 'account', group: 'account.status', saves: 'panel', control: { kind: 'carnivore-account' } },
    { id: 'install_report_privacy', section: 'account', group: 'account.privacy', saves: 'panel', control: { kind: 'install-report-privacy' } },

    { id: 'theme', section: 'appearance', group: 'appearance.colors', saves: 'instant', control: { kind: 'theme-picker' } },
    { id: 'row_icons', section: 'appearance', group: 'appearance.sidebar', saves: 'instant', control: { kind: 'row-icons' } },
    { id: 'foot_bar_layout', section: 'appearance', group: 'appearance.status_bar', saves: 'instant', control: { kind: 'foot-bar-layout', half: 'collapsed' } },
    { id: 'foot_bar_items', section: 'appearance', group: 'appearance.status_bar', saves: 'instant', control: { kind: 'foot-bar-items' } },
    { id: 'foot_bar_layout_open', section: 'appearance', group: 'appearance.control_center', saves: 'instant', control: { kind: 'foot-bar-layout', half: 'open' } },
    { id: 'animations', section: 'appearance', group: 'appearance.motion', saves: 'instant', control: { kind: 'animations' } },

    { id: 'auto_sleep', section: 'sessions', group: 'sessions.auto_sleep', saves: 'instant', control: { kind: 'auto-sleep' }, info: true },
    { id: 'auto_sleep_minutes', section: 'sessions', group: 'sessions.auto_sleep', saves: 'batch', control: { kind: 'auto-sleep-minutes' }, parent: 'auto_sleep' },
    { id: 'auto_sleep_unread_blocks', section: 'sessions', group: 'sessions.auto_sleep', saves: 'instant', control: { kind: 'auto-sleep-unread' } },
    { id: 'auto_sleep_unread_minutes', section: 'sessions', group: 'sessions.auto_sleep', saves: 'batch', control: { kind: 'auto-sleep-unread-minutes' }, parent: 'auto_sleep_unread_blocks' },
    { id: 'agent_commands', section: 'sessions', group: 'sessions.agents', saves: 'panel', control: { kind: 'link', action: 'open-wrappers' } },
    { id: 'agent_gate', section: 'sessions', group: 'sessions.agents', saves: 'panel', control: { kind: 'agent-gate' } },
    { id: 'mcp_server', section: 'sessions', group: 'sessions.agents', saves: 'panel', control: { kind: 'mcp-server' } },
    // the plugins page

    { id: 'default_shell', section: 'terminal', group: 'terminal.startup', saves: 'batch', control: { kind: 'text', field: ws('default_shell'), placeholder: '/bin/zsh' } },
    { id: 'environment', section: 'terminal', group: 'terminal.startup', saves: 'batch', control: { kind: 'env' } },
    { id: 'tui_cli', section: 'terminal', group: 'terminal.tui', saves: 'panel', control: { kind: 'tui-cli' } },
    { id: 'screen_reader', section: 'terminal', group: 'terminal.accessibility', saves: 'instant', control: { kind: 'screen-reader' } },
    { id: 'crosstalk_cards', section: 'terminal', group: 'terminal.crosstalk_cards', saves: 'instant', control: { kind: 'crosstalk-card', switch: 'enabled' } },
    { id: 'crosstalk_card_sender', section: 'terminal', group: 'terminal.crosstalk_cards', saves: 'instant', control: { kind: 'crosstalk-card', switch: 'senderCards' }, parent: 'crosstalk_cards' },
    { id: 'crosstalk_card_receiver', section: 'terminal', group: 'terminal.crosstalk_cards', saves: 'instant', control: { kind: 'crosstalk-card', switch: 'receiverCards' }, parent: 'crosstalk_cards' },
    { id: 'crosstalk_card_keep', section: 'terminal', group: 'terminal.crosstalk_cards', saves: 'instant', control: { kind: 'crosstalk-card', switch: 'keepCards' }, parent: 'crosstalk_cards' },

    { id: 'toast_style', section: 'notifications', group: 'notifications.delivery', saves: 'instant', control: { kind: 'toast-mode' } },
    { id: 'notification_destinations', section: 'notifications', group: 'notifications.channels', saves: 'panel', control: { kind: 'notify-destinations' } },
    { id: 'notification_link', section: 'notifications', group: 'notifications.routing', saves: 'panel', control: { kind: 'notify-link' } },
    { id: 'notification_matrix', section: 'notifications', group: 'notifications.routing', saves: 'panel', control: { kind: 'notify-matrix' } },
    { id: 'notification_mutes', section: 'notifications', group: 'notifications.routing', saves: 'panel', control: { kind: 'notify-mutes' } },
    { id: 'notification_sync', section: 'notifications', group: 'notifications.routing', saves: 'panel', control: { kind: 'notify-sync' } },
    { id: 'web_push', section: 'notifications', group: 'notifications.web_push', saves: 'panel', control: { kind: 'web-push' } },
    { id: 'messaging', section: 'notifications', group: 'notifications.messaging', saves: 'panel', control: { kind: 'messaging' } },

    { id: 'ai_connections', section: 'byoai', group: 'byoai.connections', saves: 'panel', control: { kind: 'ai-connections' } },
    { id: 'ai_routing', section: 'byoai', group: 'byoai.routing', saves: 'panel', control: { kind: 'ai-routing' } },
    { id: 'ai_calls', section: 'byoai', group: 'byoai.calls', saves: 'panel', control: { kind: 'ai-calls' } },

    { id: 'log_processor_cplugs', section: 'log_processor', group: 'log_processor.cplugs', saves: 'panel', control: { kind: 'pipeline-status' } },
    { id: 'deepsearch_scope', section: 'log_processor', group: 'log_processor.cplugs', saves: 'panel', control: { kind: 'deepsearch-scope' } },

    { id: 'development_root', section: 'general', group: 'general.paths', saves: 'batch', control: { kind: 'text', field: ws('development_root'), placeholder: '~/Development' } },
    { id: 'default_editor', section: 'general', group: 'general.paths', saves: 'batch', control: { kind: 'text', field: ws('default_editor'), placeholder: 'code -w' } },
    { id: 'time_zone', section: 'general', group: 'general.time', saves: 'instant', control: { kind: 'time-zone' } },

    { id: 'app_updates', section: 'general', group: 'general.updates', saves: 'panel', control: { kind: 'app-update' } },

    { id: 'bind_address', section: 'remote', group: 'remote.access', saves: 'batch', control: { kind: 'bind' } },
    { id: 'prefer_tls', section: 'remote', group: 'remote.access', saves: 'instant', control: { kind: 'config-toggle', field: { group: 'server_prefs', key: 'tls_preferred' } } },
    { id: 'phone_link', section: 'remote', group: 'remote.phone_link', saves: 'panel', control: { kind: 'phone-link' }, feature: 'phone_link' },
    { id: 'custom_domain_remove', section: 'remote', group: 'remote.phone_link', saves: 'panel', control: { kind: 'custom-domain-remove' }, feature: 'phone_link', lifecycle: true },
    { id: 'api_keys', section: 'remote', group: 'remote.api_keys', saves: 'panel', control: { kind: 'api-keys' } },

    { id: 'log_level', section: 'advanced', group: 'advanced.diagnostics', saves: 'panel', control: { kind: 'log-level' } },
    { id: 'mcp_tools', section: 'advanced', group: 'advanced.mcp_tools', saves: 'panel', control: { kind: 'mcp-tools' } },
    { id: 'beast_grid', section: 'advanced', group: 'advanced.beast_mode', saves: 'panel', control: { kind: 'beast-grid' } },
    { id: 'developer_mode', section: 'advanced', group: 'advanced.developer', saves: 'instant', control: { kind: 'config-toggle', field: { group: 'server_prefs', key: 'developer_mode' } } },
    { id: 'config_bundle', section: 'advanced', group: 'advanced.migration', saves: 'panel', control: { kind: 'config-bundle' } },
    { id: 'stats_collection', section: 'advanced', group: 'advanced.stats', saves: 'panel', control: { kind: 'stats-collection', part: 'main' } },
    { id: 'stats_clear', section: 'advanced', group: 'advanced.stats', saves: 'panel', control: { kind: 'stats-collection', part: 'lifecycle' }, lifecycle: true },
];

export function settingsIn(section: SectionId): SettingDef[] {
    return SETTINGS.filter((s) => s.section === section);
}

export function slugOf(group: GroupId): string {
    return group.slice(group.indexOf('.') + 1);
}

export function groupOfSlug(section: SectionId, slug: string): GroupId | null {
    return groupsIn(section).find((g) => slugOf(g) === slug) ?? null;
}

export function groupsIn(section: SectionId): GroupId[] {
    const seen = new Set<GroupId>();
    for (const s of settingsIn(section)) seen.add(s.group);
    return [...seen];
}

export function settingsInGroup(group: GroupId): SettingDef[] {
    return SETTINGS.filter((s) => s.group === group);
}

export function settingById(id: string): SettingDef | null {
    return SETTINGS.find((s) => s.id === id) ?? null;
}

export function settingKey(id: string, part: 'label' | 'help' | 'keywords' | 'info'): string {
    return `settings.item.${id}.${part}`;
}

export function sectionKey(id: SectionId, part: 'label' | 'hint'): string {
    return part === 'label' ? `settings.section.${id}` : `settings.section.${id}.hint`;
}

export function groupKey(id: GroupId, part: 'label' | 'hint'): string {
    return `settings.group.${id}.${part}`;
}

export function rowDomId(id: string): string {
    return `setting-${id}`;
}

export function isWideControl(control: SettingControl): boolean {
    if (control.kind === 'stats-collection' && control.part === 'lifecycle') return false;
    return !['text', 'secret', 'bind', 'theme-picker', 'custom-domain-remove', 'auto-sleep', 'auto-sleep-minutes', 'auto-sleep-unread', 'auto-sleep-unread-minutes', 'config-toggle', 'crosstalk-card', 'link'].includes(control.kind);
}
