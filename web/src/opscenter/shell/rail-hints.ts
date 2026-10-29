
export interface RailHintRow {
    id: string;
    labelKey: string;
    keys: string;
}

export const RAIL_HINT_ROWS: readonly RailHintRow[] = [
    { id: 'home', labelKey: 'opscenter.nav.home', keys: '..' },
    { id: 'hosts', labelKey: 'opscenter.nav.hosts', keys: 'h' },
    { id: 'sessions', labelKey: 'opscenter.nav.sessions', keys: 's' },
    { id: 'warroom', labelKey: 'opscenter.nav.warroom', keys: 'c' },
    { id: 'widgets', labelKey: 'opscenter.nav.widgets', keys: 'w' },
    { id: 'warez', labelKey: 'opscenter.nav.warez', keys: 'r' },
    { id: 'blueprints', labelKey: 'blueprint.title', keys: 'b' },
    { id: 'automations', labelKey: 'opscenter.nav.automations', keys: 'u' },
    { id: 'providers', labelKey: 'opscenter.nav.providers', keys: 'a' },
    { id: 'settings', labelKey: 'opscenter.nav.settings', keys: '`' },
    { id: 'wrappers', labelKey: 'opscenter.nav.wrappers', keys: 'l' },
];

export function railHint(id: string): string {
    return RAIL_HINT_ROWS.find((r) => r.id === id)?.keys ?? '';
}
