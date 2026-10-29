import {
    AdminApi,
    ApiRefusal,
    mayChangeStanding,
    disableRefusal,
    standingAction,
    adminAction,
    looksLikeCode,
    reasonRefusal,
    type EmailFlow,
    type ReportAnswer,
    type Me,
    type Refusal,
    type SubmissionRow,
    type UserRow,
} from './admin.js';
import {
    clearSessionCredential,
    readSessionCredential,
    writeSessionCredential,
} from './session-credential';
import { refusalOf } from './refusal-of';
import { DEFAULT_QUEUE_STAGE, QUEUE_STAGES, QUEUE_STATUSES, mergeNewestFirst } from './queue-stage.js';
import { PasskeyApi } from './passkey-api.js';
import type { CredentialsLike } from './passkey.js';
import { createPasskeyHost, signInCeremony, type PasskeyHost } from './passkey-host.svelte.js';

export const TOKEN_KEY = 'carnivore.admin.access_token';

const LEGACY_TOKEN_KEY = 'cloude.admin.access_token';

export type Route = 'queue' | 'users' | 'notes' | 'moderation' | 'audit' | 'system' | 'funnel';

export type Step = 'passkey' | 'email' | 'code' | 'enroll' | 'signed_in';

export interface TokenStore {
    read(): string;
    write(token: string): void;
    clear(): void;
}

export function parseRoute(hash: string): Route {
    const bare = String(hash || '').replace(/^#\/?/, '').trim().toLowerCase();
    if (bare === 'users') return 'users';
    if (bare === 'notes') return 'notes';
    if (bare === 'moderation') return 'moderation';
    if (bare === 'audit') return 'audit';
    if (bare === 'system') return 'system';
    if (bare === 'funnel') return 'funnel';
    return 'queue';
}

/* nothing at all */
export function createTokenStore(scope: unknown): TokenStore {
    function storage(): Storage | null {
        try {
            const holder = scope as { sessionStorage?: Storage } | null;
            return holder?.sessionStorage || null;
        } catch (error) {
            return null;
        }
    }
    return {
        read(): string {
            const store = storage();
            if (!store) return '';
            return readSessionCredential(store, TOKEN_KEY, LEGACY_TOKEN_KEY);
        },
        write(token: string): void {
            const store = storage();
            if (!store) return;
            writeSessionCredential(store, TOKEN_KEY, LEGACY_TOKEN_KEY, token);
        },
        clear(): void {
            const store = storage();
            if (!store) return;
            clearSessionCredential(store, TOKEN_KEY, LEGACY_TOKEN_KEY);
        },
    };
}

export interface AdminHost {
    readonly api: AdminApi;
    readonly step: Step;
    /* passkey sign in */
    readonly passkeyAvailable: boolean;
    readonly hint: string;
    readonly pk: PasskeyHost;
    readonly route: Route;
    readonly destination: string;
    readonly email: string;
    readonly me: Me | null;
    readonly refusal: Refusal | null;
    readonly busy: boolean;
    readonly users: UserRow[];
    readonly usersCursor: string;
    readonly usersLoaded: boolean;
    readonly queueStatus: string;
    readonly submissions: SubmissionRow[];
    readonly queueLoaded: boolean;
    readonly rejecting: string;
    readonly rejectReason: string;
    readonly overriding: string;
    readonly overrideReason: string;
    readonly revoking: string;
    readonly revokeReason: string;
    readonly reports: Record<string, ReportAnswer>;
    readonly disabling: string;
    readonly disableReason: string;
    setRoute(hash: string): void;
    signInPasskey(): Promise<void>;
    useEmail(): void;
    usePasskey(): void;
    start(email: string): Promise<void>;
    submitCode(code: string): Promise<void>;
    restart(): void;
    signOut(): void;
    adopt(): Promise<void>;
    loadUsers(more: boolean): Promise<void>;
    toggleStanding(row: UserRow): Promise<void>;
    toggleAdmin(row: UserRow): Promise<void>;
    mayChange(row: UserRow): boolean;
    standingFor(row: UserRow): 'enable' | 'disable';
    adminFor(row: UserRow): 'grant' | 'revoke';
    loadQueue(status: string): Promise<void>;
    selectQueueStage(tab: string): void;
    approve(id: string): Promise<void>;
    beginReject(id: string): void;
    setRejectReason(reason: string): void;
    cancelReject(): void;
    confirmReject(): Promise<void>;
    loadReport(id: string): Promise<void>;
    beginOverride(id: string): void;
    setOverrideReason(reason: string): void;
    cancelOverride(): void;
    confirmOverride(): Promise<void>;
    setRevokeReason(id: string, reason: string): void;
    confirmRevoke(): Promise<void>;
    regate(id: string): Promise<void>;
    setDisableReason(reason: string): void;
    cancelDisable(): void;
    confirmDisable(): Promise<void>;
}

function asBrowserOptions<T>(decoded: unknown): T {
    return decoded as T;
}

function browserCredentials(): CredentialsLike | undefined {
    const credentials = globalThis.navigator?.credentials;
    if (!credentials) return undefined;
    return {
        get: (options) => credentials.get({ publicKey: asBrowserOptions<PublicKeyCredentialRequestOptions>(options.publicKey) }),
        create: (options) => credentials.create({ publicKey: asBrowserOptions<PublicKeyCredentialCreationOptions>(options.publicKey) }),
    };
}

export function createHost(deps: {
    api: AdminApi;
    tokens: TokenStore;
    credentials?: () => CredentialsLike | undefined;
}): AdminHost {
    const { api, tokens } = deps;
    const creds = deps.credentials ?? browserCredentials;
    const passkeyApi = new PasskeyApi(api);

    let step = $state<Step>('email');
    let passkeyAvailable = $state(false);
    let hint = $state('');
    let route = $state<Route>('queue');
    let email = $state('');
    let destination = $state('');
    let flow = $state<EmailFlow | null>(null);
    let me = $state<Me | null>(null);
    let refusal = $state<Refusal | null>(null);
    let busy = $state(false);
    let users = $state<UserRow[]>([]);
    let usersCursor = $state('');
    let usersLoaded = $state(false);
    let queueStatus = $state<string>(DEFAULT_QUEUE_STAGE);
    let submissions = $state<SubmissionRow[]>([]);
    let queueLoaded = $state(false);
    let rejecting = $state('');
    let rejectReason = $state('');
    let overriding = $state('');
    let overrideReason = $state('');
    let revoking = $state('');
    let revokeReason = $state('');
    let reports = $state<Record<string, ReportAnswer>>({});
    let disabling = $state('');
    let disableReason = $state('');

    function reset(): void {
        tokens.clear();
        step = passkeyAvailable ? 'passkey' : 'email';
        hint = '';
        flow = null;
        destination = '';
        me = null;
        users = [];
        usersCursor = '';
        usersLoaded = false;
        submissions = [];
        queueLoaded = false;
        rejecting = '';
        rejectReason = '';
        overriding = '';
        overrideReason = '';
        revoking = '';
        revokeReason = '';
        reports = {};
        disabling = '';
        disableReason = '';
    }

    async function guard(work: () => Promise<void>): Promise<boolean> {
        busy = true;
        refusal = null;
        try {
            await work();
            return true;
        } catch (error) {
            const shaped = refusalOf(error);
            if (shaped.status === 401) reset();
            else if (shaped.code === 'passkey_required') {
                passkeyAvailable = true;
                reset();
            }
            refusal = shaped;
            return false;
        } finally {
            busy = false;
        }
    }

    async function loadUsers(more: boolean): Promise<void> {
        if (!me?.is_admin) return;
        const cursor = more ? usersCursor : '';
        await guard(async () => {
            const page = await api.users(cursor);
            users = more ? [...users, ...page.users] : page.users;
            usersCursor = page.cursor;
            usersLoaded = true;
        });
    }

    async function loadQueue(tab: string): Promise<void> {
        if (!me?.is_admin) return;
        if (QUEUE_STAGES.some((stage) => stage.id === tab)) queueStatus = tab;
        await guard(async () => {
            const lists = [];
            for (const status of QUEUE_STATUSES) lists.push(await api.submissions(status));
            submissions = mergeNewestFirst(lists);
            queueLoaded = true;
        });
    }

    function selectQueueStage(tab: string): void {
        if (QUEUE_STAGES.some((stage) => stage.id === tab)) queueStatus = tab;
    }

    /* passkey sign in */
    async function reauth(): Promise<void> {
        tokens.write(await signInCeremony(passkeyApi, creds()));
    }

    const pk = createPasskeyHost({
        pk: passkeyApi,
        creds,
        guard,
        reauth,
        onEnrolled: () => {
            step = 'signed_in';
        },
    });

    async function afterEmailSignIn(): Promise<void> {
        if (!passkeyAvailable) return;
        try {
            const status = await passkeyApi.credentials();
            if (status.enrolled) {
                tokens.clear();
                me = null;
                hint = 'use_passkey';
                step = 'passkey';
            } else if (status.can_enroll_first) {
                step = 'enroll';
            }
        } catch (error) {
            if (error instanceof ApiRefusal && error.refusal.status === 401) throw error;
        }
    }

    return {
        api,
        pk,
        get passkeyAvailable() {
            return passkeyAvailable;
        },
        get hint() {
            return hint;
        },
        get step() {
            return step;
        },
        get route() {
            return route;
        },
        get destination() {
            return destination;
        },
        get email() {
            return email;
        },
        get me() {
            return me;
        },
        get refusal() {
            return refusal;
        },
        get busy() {
            return busy;
        },
        get users() {
            return users;
        },
        get usersCursor() {
            return usersCursor;
        },
        get usersLoaded() {
            return usersLoaded;
        },
        get queueStatus() {
            return queueStatus;
        },
        get submissions() {
            return submissions;
        },
        get queueLoaded() {
            return queueLoaded;
        },
        get rejecting() {
            return rejecting;
        },
        get rejectReason() {
            return rejectReason;
        },
        get overriding() {
            return overriding;
        },
        get revoking() {
            return revoking;
        },
        get revokeReason() {
            return revokeReason;
        },
        get overrideReason() {
            return overrideReason;
        },
        get reports() {
            return reports;
        },
        get disabling() {
            return disabling;
        },
        get disableReason() {
            return disableReason;
        },

        setRoute(hash: string): void {
            route = parseRoute(hash);
        },

        async signInPasskey(): Promise<void> {
            await guard(async () => {
                tokens.write(await signInCeremony(passkeyApi, creds()));
                hint = '';
                step = 'signed_in';
                me = await api.me();
            });
        },

        useEmail(): void {
            refusal = null;
            step = 'email';
        },

        usePasskey(): void {
            refusal = null;
            step = 'passkey';
        },

        async start(address: string): Promise<void> {
            const wanted = String(address || '').trim().toLowerCase();
            email = wanted;
            await guard(async () => {
                const answer = await api.start(wanted);
                flow = answer;
                destination = answer.destination;
                step = 'code';
            });
        },

        async submitCode(code: string): Promise<void> {
            const typed = String(code || '').trim();
            if (!looksLikeCode(typed)) {
                refusal = { status: 0, code: 'code_not_digits', params: {} };
                return;
            }
            const pending = flow;
            if (!pending) {
                refusal = { status: 0, code: 'unknown_flow', params: {} };
                return;
            }
            await guard(async () => {
                const answer = await api.verify(email, pending, typed);
                tokens.write(answer.access_token);
                flow = null;
                step = 'signed_in';
                me = await api.me();
                await afterEmailSignIn();
            });
        },

        restart(): void {
            flow = null;
            destination = '';
            refusal = null;
            step = 'email';
        },

        signOut(): void {
            reset();
            refusal = null;
        },

        async adopt(): Promise<void> {
            if (!tokens.read()) {
                try {
                    passkeyAvailable = await passkeyApi.health();
                    if (passkeyAvailable && step === 'email') step = 'passkey';
                } catch (error) {
                    passkeyAvailable = false;
                }
                return;
            }
            step = 'signed_in';
            await guard(async () => {
                me = await api.me();
            });
        },

        loadUsers,

        async toggleStanding(row: UserRow): Promise<void> {
            if (!mayChangeStanding(row, me)) {
                refusal = { status: 0, code: 'self_change', params: {} };
                return;
            }
            const wanted = standingAction(row);
            if (wanted === 'disable') {
                disabling = row.user_id;
                disableReason = '';
                refusal = null;
                return;
            }
            const ok = await guard(async () => {
                await api.setStanding(row.user_id, wanted);
            });
            if (ok) await loadUsers(false);
        },

        setDisableReason(reason: string): void {
            disableReason = reason;
        },

        cancelDisable(): void {
            disabling = '';
            disableReason = '';
        },

        async confirmDisable(): Promise<void> {
            const local = disableRefusal(disableReason);
            if (local) {
                refusal = local;
                return;
            }
            const id = disabling;
            const reason = disableReason;
            const ok = await guard(async () => {
                await api.setStanding(id, 'disable', reason);
            });
            if (ok) {
                disabling = '';
                disableReason = '';
                await loadUsers(false);
            }
        },

        async toggleAdmin(row: UserRow): Promise<void> {
            if (!mayChangeStanding(row, me)) {
                refusal = { status: 0, code: 'self_change', params: {} };
                return;
            }
            const wanted = adminAction(row) === 'grant';
            const ok = await guard(async () => {
                await api.setAdmin(row.user_id, wanted);
            });
            if (ok) await loadUsers(false);
        },

        mayChange(row: UserRow): boolean {
            return mayChangeStanding(row, me);
        },

        standingFor(row: UserRow): 'enable' | 'disable' {
            return standingAction(row);
        },

        adminFor(row: UserRow): 'grant' | 'revoke' {
            return adminAction(row);
        },

        loadQueue,
        selectQueueStage,

        async approve(id: string): Promise<void> {
            const seen = reports[id]?.report_sha256 || '';
            const ok = await guard(async () => {
                await api.approve(id, seen);
            });
            if (ok) await loadQueue(queueStatus);
        },

        beginReject(id: string): void {
            rejecting = id;
            rejectReason = '';
            refusal = null;
        },

        setRejectReason(reason: string): void {
            rejectReason = reason;
        },

        cancelReject(): void {
            rejecting = '';
            rejectReason = '';
        },

        async confirmReject(): Promise<void> {
            const local = reasonRefusal(rejectReason);
            if (local) {
                refusal = local;
                return;
            }
            const id = rejecting;
            const reason = rejectReason;
            const ok = await guard(async () => {
                await api.reject(id, reason);
            });
            if (ok) {
                rejecting = '';
                rejectReason = '';
                await loadQueue(queueStatus);
            }
        },

        async loadReport(id: string): Promise<void> {
            await guard(async () => {
                const answer = await api.report(id);
                reports = { ...reports, [id]: answer };
            });
        },

        beginOverride(id: string): void {
            overriding = id;
            overrideReason = '';
            refusal = null;
        },

        setOverrideReason(reason: string): void {
            overrideReason = reason;
        },

        cancelOverride(): void {
            overriding = '';
            overrideReason = '';
        },

        async confirmOverride(): Promise<void> {
            const local = reasonRefusal(overrideReason, 'override_needs_reason');
            if (local) {
                refusal = local;
                return;
            }
            const id = overriding;
            const reason = overrideReason;
            const seen = reports[id]?.report_sha256 || '';
            const ok = await guard(async () => {
                await api.override(id, reason, seen);
            });
            if (ok) {
                overriding = '';
                overrideReason = '';
                await loadQueue(queueStatus);
            }
        },

        setRevokeReason(id: string, reason: string): void {
            if (revoking !== id) refusal = null;
            revoking = id;
            revokeReason = reason;
        },

        async confirmRevoke(): Promise<void> {
            const local = reasonRefusal(revokeReason, 'revoke_needs_reason');
            if (local) {
                refusal = local;
                return;
            }
            const id = revoking;
            const reason = revokeReason;
            const ok = await guard(async () => {
                await api.revoke(id, reason);
            });
            if (ok) {
                revoking = '';
                revokeReason = '';
                await loadQueue(queueStatus);
            }
        },

        async regate(id: string): Promise<void> {
            const ok = await guard(async () => {
                await api.regate(id);
            });
            if (ok) await loadQueue(queueStatus);
        },
    };
}
