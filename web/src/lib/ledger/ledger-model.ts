import type { Translate } from '../sessions/types';
import { switchRank, type AccountSwitchState } from '../account-switch/switch-model';

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

export const LOGIN_EXPIRY_NOTICE_DAYS = 14;
export const LOGIN_EXPIRY_URGENT_DAYS = 3;

export const LEDGER_KEYS = {
    screenTitle: 'ledger.screen.title',
    screenOpen: 'ledger.screen.open',
    columnProvider: 'ledger.column.provider',
    columnPlan: 'ledger.column.plan',
    columnIdentity: 'ledger.column.identity',
    columnFetched: 'ledger.column.fetched',
    columnActions: 'ledger.column.actions',
    accountsLabel: 'ledger.accounts.label',
    windowHead: 'ledger.window.head',
    windowUsedHead: 'ledger.window.used_head',
    windowResetsHead: 'ledger.window.resets_head',
    meterLabel: 'ledger.meter.label',
    totalLabel: 'ledger.total.label',
    totalAccounts: 'ledger.total.accounts',
    loading: 'ledger.loading',
    unavailable: 'ledger.unavailable',
    emptyTitle: 'ledger.empty.title',
    emptyBody: 'ledger.empty.body',
    keepaliveLabel: 'ledger.keepalive.label',
    keepaliveInfo: 'ledger.keepalive.info',
    windowsNone: 'ledger.windows.none',
    loopAlive: 'ledger.loop.alive',
    loopStopped: 'ledger.loop.stopped',
    peerLabel: 'ledger.peer.label',
    peerShared: 'ledger.peer.shared',
    peerUnavailable: 'ledger.peer.unavailable',
    accountError: 'ledger.account.error',
    percent: 'ledger.percent',
    fetched: 'ledger.fetched',
    tagManaged: 'ledger.tag.managed',
    headroomLabel: 'ledger.headroom.label',
    notMeasured: 'ledger.headroom.not_measured',
    valueUnknown: 'ledger.value.unknown',
    resetPassed: 'ledger.reset.passed',
    resetSeconds: 'ledger.reset.seconds',
    resetMinutes: 'ledger.reset.minutes',
    resetHours: 'ledger.reset.hours',
    resetHoursMinutes: 'ledger.reset.hours_minutes',
    resetDays: 'ledger.reset.days',
    resetDaysHours: 'ledger.reset.days_hours',
    ageNever: 'ledger.age.never',
    ageSeconds: 'ledger.age.seconds',
    ageMinutes: 'ledger.age.minutes',
    ageHours: 'ledger.age.hours',
    ageDays: 'ledger.age.days',
    credentialOk: 'ledger.credential.ok',
    credentialExpired: 'ledger.credential.expired',
    credentialMissing: 'ledger.credential.missing',
    credentialRefused: 'ledger.credential.refused',
    credentialRateLimited: 'ledger.credential.rate_limited',
    credentialError: 'ledger.credential.error',
    credentialUnknown: 'ledger.credential.unknown',
    credentialUnrecognised: 'ledger.credential.unrecognised',
    editorSummary: 'ledger.editor.summary',
    editorNameLabel: 'ledger.editor.name_label',
    editorNamePlaceholder: 'ledger.editor.name_placeholder',
    editorIdLabel: 'ledger.editor.id_label',
    editorIdHelp: 'ledger.editor.id_help',
    editorProviderLabel: 'ledger.editor.provider_label',
    editorProviderClaude: 'ledger.editor.provider_claude',
    editorProviderCodex: 'ledger.editor.provider_codex',
    editorClaudeDirLabel: 'ledger.editor.claude_dir_label',
    editorClaudeDirHelp: 'ledger.editor.claude_dir_help',
    editorCodexHomeLabel: 'ledger.editor.codex_home_label',
    editorCodexHomeHelp: 'ledger.editor.codex_home_help',
    editorSubmit: 'ledger.editor.submit',
    editorSubmitting: 'ledger.editor.submitting',
    editorNameBlank: 'ledger.editor.name_blank',
    editorIdBlank: 'ledger.editor.id_blank',
    editorIdTaken: 'ledger.editor.id_taken',
    editorPathBlank: 'ledger.editor.path_blank',
    editorFailed: 'ledger.editor.failed',
    editorFieldRefusal: 'ledger.editor.field_refusal',
    editorRemove: 'ledger.editor.remove',
    builtInLogin: 'ledger.account.built_in_login',
    builtInRename: 'ledger.account.rename',
    builtInRenameLabel: 'ledger.account.rename_label',
    builtInRenameSave: 'ledger.account.rename_save',
    builtInRenameCancel: 'ledger.account.rename_cancel',
    editorRemoveConfirm: 'ledger.editor.remove_confirm',
    editorRemoveConfirmManaged: 'ledger.editor.remove_confirm_managed',
    editorRemoveYes: 'ledger.editor.remove_yes',
    editorRemoveCancel: 'ledger.editor.remove_cancel',
    editorRemoving: 'ledger.editor.removing',
    editorRemoveFailed: 'ledger.editor.remove_failed',
    editorRemoveDirRefused: 'ledger.editor.remove_dir_refused',

    editStart: 'ledger.edit.start',
    editOpen: 'ledger.edit.open',
    editTitle: 'ledger.edit.title',
    editManagedLabel: 'ledger.edit.managed_label',
    editManagedYes: 'ledger.edit.managed_yes',
    editManagedNo: 'ledger.edit.managed_no',
    editImmutableHelp: 'ledger.edit.immutable_help',
    editSave: 'ledger.edit.save',
    editSaving: 'ledger.edit.saving',
    editCancel: 'ledger.edit.cancel',
    editFailed: 'ledger.edit.failed',
    editNoRow: 'ledger.edit.no_row',

    colorLabel: 'ledger.color.label',
    colorNone: 'ledger.color.none',
    colorCustom: 'ledger.color.custom_label',
    colorReadout: 'ledger.color.readout',
    colorReadoutNone: 'ledger.color.readout_none',
    colorReadoutCustom: 'ledger.color.readout_custom',
    colorCellLabel: 'ledger.color.cell_label',
    colorHexLabel: 'ledger.color.hex_label',
    colorHexInvalid: 'ledger.color.hex_invalid',
    colorLedNote: 'ledger.color.led_note',
    editShortNameLabel: 'ledger.edit.short_name_label',
    editShortNamePlaceholder: 'ledger.edit.short_name_placeholder',

    editorAdvanced: 'ledger.editor.advanced',
    editorManagedHelp: 'ledger.editor.managed_help',

    loginStart: 'ledger.login.start',
    loginAgain: 'ledger.login.again',
    loginStarting: 'ledger.login.starting',
    loginInProgress: 'ledger.login.in_progress',
    loginDeviceAuth: 'ledger.login.device_auth',
    loginDirUnavailable: 'ledger.login.dir_unavailable',
    loginFailed: 'ledger.login.failed',

    pokeFailed: 'ledger.poke.failed',
    pokeUnknown: 'ledger.poke.unknown',
    pokeNeedsLogin: 'ledger.poke.needs_login',
    loginCountdownDays: 'ledger.login_countdown.days',
    loginCountdownHours: 'ledger.login_countdown.hours',
    loginCountdownExpired: 'ledger.login_countdown.expired',
} as const;

export interface LedgerWindow {
    kind: string;
    label?: string | null;
    used_pct?: number | null;
    window_seconds?: number | null;
    resets_at?: string | null;
}

export interface LedgerAccount {
    id: string;
    name?: string | null;
    provider: string;
    plan?: string | null;
    identity?: string | null;
    credential_state?: string | null;
    fetched_at?: string | null;
    next_poll_at?: string | null;
    error?: string | null;
    windows?: LedgerWindow[] | null;
    color?: string | null;
    managed?: boolean | null;
    login_expires_at?: string | null;
    poke?: LedgerPoke | null;
    setup_complete?: boolean | null;
}

export interface LedgerPoke {
    state?: string | null;
    last_at?: string | null;
    error?: string | null;
}

export interface LedgerTotalWindow extends LedgerWindow {
    accounts?: number | null;
}

export interface LedgerTotal {
    accounts?: number | null;
    windows?: LedgerTotalWindow[] | null;
}

export interface LedgerLoop {
    alive?: boolean | null;
    last_pass_at?: string | null;
}

export interface PeerLedgerAccount {
    name: string;
    provider: string;
    plan?: string | null;
    credential_state?: string | null;
    windows?: LedgerWindow[] | null;
    shared?: boolean;
}

export interface PeerLedger {
    host_label: string;
    accounts: PeerLedgerAccount[];
}

export interface PeersLedger {
    peers?: PeerLedger[] | null;
    peer_unavailable?: { host_label: string }[] | null;
}

export interface ProviderLedger {
    accounts?: LedgerAccount[] | null;
    total?: LedgerTotal | null;
    loop?: LedgerLoop | null;
}

function deltaSeconds(iso: string | null | undefined, nowMs: number): number | null {
    if (typeof iso !== 'string' || !iso.trim()) return null;
    const at = Date.parse(iso);
    if (!Number.isFinite(at)) return null;
    return Math.round((at - nowMs) / 1000);
}

export function formatResetIn(
    resetsAt: string | null | undefined,
    nowMs: number,
    t: Translate,
): string {
    const delta = deltaSeconds(resetsAt, nowMs);
    if (delta === null) return t(LEDGER_KEYS.valueUnknown);
    if (delta <= 0) return t(LEDGER_KEYS.resetPassed);
    if (delta < MINUTE) return t(LEDGER_KEYS.resetSeconds, { seconds: delta });
    if (delta < HOUR) return t(LEDGER_KEYS.resetMinutes, { minutes: Math.floor(delta / MINUTE) });
    if (delta < DAY) {
        const hours = Math.floor(delta / HOUR);
        const minutes = Math.floor((delta % HOUR) / MINUTE);
        return minutes === 0
            ? t(LEDGER_KEYS.resetHours, { hours })
            : t(LEDGER_KEYS.resetHoursMinutes, { hours, minutes });
    }
    const days = Math.floor(delta / DAY);
    const hours = Math.floor((delta % DAY) / HOUR);
    return hours === 0
        ? t(LEDGER_KEYS.resetDays, { days })
        : t(LEDGER_KEYS.resetDaysHours, { days, hours });
}

export function formatAge(
    iso: string | null | undefined,
    nowMs: number,
    t: Translate,
): string {
    const delta = deltaSeconds(iso, nowMs);
    if (delta === null) return t(LEDGER_KEYS.ageNever);
    const ago = Math.max(0, -delta);
    if (ago < MINUTE) return t(LEDGER_KEYS.ageSeconds, { seconds: ago });
    if (ago < HOUR) return t(LEDGER_KEYS.ageMinutes, { minutes: Math.floor(ago / MINUTE) });
    if (ago < DAY) return t(LEDGER_KEYS.ageHours, { hours: Math.floor(ago / HOUR) });
    return t(LEDGER_KEYS.ageDays, { days: Math.floor(ago / DAY) });
}

export function formatWindowLabel(
    window: LedgerWindow | LedgerTotalWindow | null | undefined,
    t: Translate,
): string {
    if (!window) return t(LEDGER_KEYS.valueUnknown);
    const label = typeof window.label === 'string' ? window.label.trim() : '';
    if (label) return label;
    const kind = typeof window.kind === 'string' ? window.kind.trim() : '';
    if (kind) return kind;
    return t(LEDGER_KEYS.valueUnknown);
}

function isReading(pct: number | null | undefined): pct is number {
    return typeof pct === 'number' && Number.isFinite(pct);
}

export function formatPercent(pct: number | null | undefined, t: Translate): string {
    if (!isReading(pct)) return t(LEDGER_KEYS.valueUnknown);
    return t(LEDGER_KEYS.percent, { percent: Math.round(pct) });
}

const CREDENTIAL_KEYS: Record<string, string> = {
    ok: LEDGER_KEYS.credentialOk,
    expired: LEDGER_KEYS.credentialExpired,
    missing: LEDGER_KEYS.credentialMissing,
    refused: LEDGER_KEYS.credentialRefused,
    rate_limited: LEDGER_KEYS.credentialRateLimited,
    error: LEDGER_KEYS.credentialError,
    unknown: LEDGER_KEYS.credentialUnknown,
};

const CREDENTIAL_TONES: Record<string, string> = {
    ok: 'ok',
    rate_limited: 'warn',
    expired: 'warn',
    missing: 'high',
    refused: 'high',
    error: 'high',
    unknown: 'unknown',
};

export function credentialLabel(state: string | null | undefined, t: Translate): string {
    if (typeof state !== 'string' || !state.trim()) return t(LEDGER_KEYS.credentialUnknown);
    const key = CREDENTIAL_KEYS[state];
    if (key) return t(key);
    return t(LEDGER_KEYS.credentialUnrecognised, { state });
}

export function credentialTone(state: string | null | undefined): string {
    if (typeof state !== 'string') return 'unknown';
    return CREDENTIAL_TONES[state] ?? 'unknown';
}

export function sortAccounts(
    accounts: readonly LedgerAccount[],
    state: AccountSwitchState | null = null,
): LedgerAccount[] {
    const text = (value: string | null | undefined): string =>
        typeof value === 'string' ? value : '';
    return accounts
        .map((account, index) => ({ account, index }))
        .sort((left, right) => {
            const provider = text(left.account.provider).localeCompare(
                text(right.account.provider),
            );
            if (provider !== 0) return provider;
            const l = switchRank(state, { id: text(left.account.id), provider: text(left.account.provider) });
            const r = switchRank(state, { id: text(right.account.id), provider: text(right.account.provider) });
            if (l !== r) return l === Infinity ? 1 : r === Infinity ? -1 : l - r;
            const name = text(left.account.name).localeCompare(text(right.account.name));
            if (name !== 0) return name;
            return left.index - right.index;
        })
        .map((entry) => entry.account);
}

export function loginExpiryTone(
    iso: string | null | undefined,
    nowMs: number,
): string | null {
    const delta = deltaSeconds(iso, nowMs);
    if (delta === null) return null;
    if (delta <= 0) return 'high';
    if (delta >= LOGIN_EXPIRY_NOTICE_DAYS * DAY) return null;
    return delta < LOGIN_EXPIRY_URGENT_DAYS * DAY ? 'high' : 'warn';
}

export function pokeFailure(account: LedgerAccount, t: Translate): string | null {
    const poke = account.poke;
    if (poke?.state === 'needs_login') return t(LEDGER_KEYS.pokeNeedsLogin);
    if (!poke || (poke.state !== 'failed' && poke.state !== 'unknown')) return null;
    const detail = typeof poke.error === 'string' ? poke.error.trim() : '';
    if (!detail) return null;
    const key = poke.state === 'unknown' ? LEDGER_KEYS.pokeUnknown : LEDGER_KEYS.pokeFailed;
    return t(key, { detail });
}

export function formatLoginCountdown(
    iso: string | null | undefined,
    nowMs: number,
    t: Translate,
): string | null {
    const delta = deltaSeconds(iso, nowMs);
    if (delta === null) return null;
    if (delta <= 0) return t(LEDGER_KEYS.loginCountdownExpired);
    if (delta >= DAY) return t(LEDGER_KEYS.loginCountdownDays, { count: Math.floor(delta / DAY) });
    return t(LEDGER_KEYS.loginCountdownHours, { count: Math.max(1, Math.floor(delta / HOUR)) });
}

export function removeConfirmKey(account: Pick<LedgerAccount, 'managed'>): string {
    return account.managed === true
        ? LEDGER_KEYS.editorRemoveConfirmManaged
        : LEDGER_KEYS.editorRemoveConfirm;
}

export const BUILT_IN_ACCOUNT_ID = 'auto-claude-default';

export function isBuiltInLogin(account: Pick<LedgerAccount, 'id'>): boolean {
    return account.id === BUILT_IN_ACCOUNT_ID;
}

export interface WorstWindow {
    pct: number;
    window: LedgerWindow;
}

export function worstWindow(account: Pick<LedgerAccount, 'windows'>): WorstWindow | null {
    let worst: WorstWindow | null = null;
    for (const window of account.windows ?? []) {
        if (!isReading(window.used_pct)) continue;
        if (worst === null || window.used_pct > worst.pct) worst = { pct: window.used_pct, window };
    }
    return worst;
}

export function rankByHeadroom(accounts: readonly LedgerAccount[]): LedgerAccount[] {
    return accounts
        .map((account, index) => ({ account, index, pct: worstWindow(account)?.pct ?? null }))
        .sort((a, b) => {
            if (a.pct === null && b.pct === null) return a.index - b.index;
            if (a.pct === null) return 1;
            if (b.pct === null) return -1;
            return b.pct - a.pct || a.index - b.index;
        })
        .map((entry) => entry.account);
}
