import type { Translate } from '../sessions/types';
import type { CplugItem } from './cplugs-adapter';

export interface HealthRow {
    readonly id: string;
    readonly kind: 'feature' | 'plugin' | 'claude_code_plugin';
    readonly source: string;
    readonly word: 'on' | 'off' | 'needs_approval' | 'held';
    readonly reason: string | null;
    readonly button: string | null;
    readonly version: string | null;
    readonly data_bytes: number;
    readonly api_version?: number | null;
}

export interface HealthReport {
    readonly rows: readonly HealthRow[];
}

export type HealthTone = 'on' | 'warn' | 'off';

const WORD_KEYS: Readonly<Record<HealthRow['word'], string>> = {
    on: 'plugins.page.health.word.on',
    off: 'plugins.page.health.word.off',
    needs_approval: 'plugins.page.health.word.needs_approval',
    held: 'plugins.page.health.word.held',
};

const REASON_KEYS: Readonly<Record<string, string>> = {
    new_install: 'plugins.page.health.reason.new_install',
    grant_waiting: 'plugins.page.health.reason.grant_waiting',
    code_changed: 'plugins.page.health.reason.code_changed',
    changed_on_disk: 'plugins.page.health.reason.changed_on_disk',
    safe_mode: 'plugins.page.health.reason.safe_mode',
    third_party_off: 'plugins.page.health.reason.third_party_off',
    sideload_off: 'plugins.page.health.reason.sideload_off',
    revoked: 'plugins.page.health.reason.revoked',
    index_expired: 'plugins.page.health.reason.index_expired',
    trust_refused: 'plugins.page.health.reason.trust_refused',
    needs_plugin: 'plugins.page.health.reason.needs_plugin',
    folder_unreadable: 'plugins.page.health.reason.folder_unreadable',
    folder_missing: 'plugins.page.health.reason.folder_missing',
    manifest_invalid: 'plugins.page.health.reason.manifest_invalid',
    install_record_missing: 'plugins.page.health.reason.install_record_missing',
    crashed: 'plugins.page.health.reason.crashed',
    unavailable: 'plugins.page.health.reason.unavailable',
    runtime_down: 'plugins.page.health.reason.runtime_down',
};

const BUTTON_KEYS: Readonly<Record<string, string>> = {
    turn_off: 'plugins.page.health.button.turn_off',
    turn_on: 'plugins.page.health.button.turn_on',
    review: 'plugins.page.health.button.review',
    leave_safe_mode: 'plugins.page.health.button.leave_safe_mode',
    turn_on_third_party: 'plugins.page.health.button.turn_on_third_party',
    turn_on_developer: 'plugins.page.health.button.turn_on_developer',
    open_catalog: 'plugins.page.health.button.open_catalog',
    turn_on_needed_plugin: 'plugins.page.health.button.turn_on_needed_plugin',
    show_log: 'plugins.page.health.button.show_log',
};

export function healthOf(report: HealthReport | null, plugin: Pick<CplugItem, 'cplugId' | 'publisher'>): HealthRow | undefined {
    if (!report) return undefined;
    const rows = report.rows.filter((row) => row.kind !== 'claude_code_plugin');
    return rows.find((row) => row.id === plugin.cplugId) ?? rows.find((row) => plugin.publisher && row.id === `${plugin.publisher}/${plugin.cplugId}`);
}

export function claudeCodeRows(report: HealthReport | null): HealthRow[] {
    return report ? report.rows.filter((row) => row.kind === 'claude_code_plugin') : [];
}

export function wordOf(row: HealthRow, t: Translate): string {
    return t(WORD_KEYS[row.word]);
}

export function reasonOf(row: HealthRow, t: Translate): string | null {
    const key = row.reason ? REASON_KEYS[row.reason] : undefined;
    return key ? t(key) : null;
}

const CONTRACT_KEY = 'plugins.page.health.contract';

export function contractOf(row: HealthRow, t: Translate): string | null {
    return typeof row.api_version === 'number' ? t(CONTRACT_KEY, { version: row.api_version }) : null;
}

export function buttonLabelOf(row: HealthRow, t: Translate): string | null {
    const key = row.button ? BUTTON_KEYS[row.button] : undefined;
    return key ? t(key) : null;
}

export function toneOf(row: Pick<HealthRow, 'word'>): HealthTone {
    if (row.word === 'on') return 'on';
    return row.word === 'off' ? 'off' : 'warn';
}
