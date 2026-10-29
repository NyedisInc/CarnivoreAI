import type { RestartAccounts } from '../launch-picker/account-types';
import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type Harness = 'claude' | 'codex' | 'shell' | 'hermes' | 'openclaw' | 'local';
export type Posture = 'harness_default' | 'ask' | 'accept_edits' | 'skip_all';

export interface LaunchProfile {
    id: string;
    harness: Harness;
    label: string;
    icon: string | null;
    description: string | null;
    default: boolean;
    account: { mode: 'follow_active' | 'pinned'; account_id: string | null };
    endpoint: { mode: 'native' | 'connection'; connection_id: string | null };
    model: { mode: 'default' | 'fixed' | 'ask'; value: string | null };
    permissions: Posture;
    flags: string[];
    env: { name: string; value: string }[];
    secrets: { name: string; keychain_ref: string }[];
    shell_profile: boolean;
    before_launch: string | null;
    custom_command: { script: string; entry: string | null } | null;
    custom_command_ack_no_args: boolean;
}

export interface ProfileRow extends LaunchProfile {
    summary: { permissions_badge: string; model: string; account: string; endpoint: string };
}

export interface ProfileList { revision: number; profiles: ProfileRow[] }

export interface Preview {
    profile_id: string;
    command: string;
    argv_tail: string[];
    env_set: { name: string; value: string }[];
    env_unset: string[];
    secrets: { name: string; keychain_ref: string; key_hint: string | null }[];
    script: string | null;
    display: { label: string; harness: string; account: string; model: string; permissions: string; endpoint: string | null };
    digest: string;
}

export interface CheckResult {
    profile_id: string;
    binary: { status: string; output?: string; detail?: string; [k: string]: unknown };
    endpoint?: { connection_id: string; ok: boolean; detail?: string; error?: string; models: number };
}

export interface UsageResult { profile_id: string; counts: Record<string, number>; total: number }

export interface ImportPreview {
    profile: LaunchProfile;
    sha256: string;
    parts: { kind: string; text: string }[];
    exists: boolean;
    existing_is_default: boolean;
    endpoint_connection_missing: boolean;
}

export interface ComputerLauncher { id: string; name: string; family: string }
/* could not */
export type ComputerLaunchers = { status: 'ok'; launchers: ComputerLauncher[] } | { status: 'ssh'; families: string[] } | { status: 'unavailable'; reason: string };
export interface AccountOption { id: string; name: string; provider: string }
export interface ConnectionOption { id: string; preset: string; label: string; enabled: boolean; has_key: boolean; key_hint: string }
export interface ModelOption { id: string; label: string }

export interface DeleteRefusal { code: string; message: string; counts: Record<string, number> }

const R = '/launch-profiles';
const seg = (id: string): string => encodeURIComponent(id);
const json = (body: unknown): string => JSON.stringify(body);

export function errorText(err: unknown): string {
    if (!(err instanceof ApiError)) return err instanceof Error ? err.message : String(err);
    const body = err.payload as { detail?: unknown } | null;
    const detail = body && typeof body === 'object' ? body.detail : undefined;
    if (Array.isArray(detail)) {
        const lines = detail.map((d) => {
            const row = d as { loc?: unknown[]; msg?: string };
            const where = (row.loc ?? []).filter((p) => p !== 'body').join('.');
            return where ? `${where}: ${row.msg ?? ''}` : `${row.msg ?? ''}`;
        });
        return lines.filter(Boolean).join('; ') || err.message;
    }
    if (detail && typeof detail === 'object') {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === 'string' && message) return message;
    }
    return err.message;
}

export function deleteRefusal(err: unknown): DeleteRefusal | null {
    if (!(err instanceof ApiError) || err.status !== 409) return null;
    const detail = (err.payload as { detail?: Record<string, unknown> } | null)?.detail;
    if (!detail || (detail.code !== 'in_use' && detail.code !== 'is_default')) return null;
    return { code: String(detail.code), message: String(detail.message ?? ''), counts: (detail.counts as Record<string, number>) ?? {} };
}

export function createLaunchProfilesApi(f: Fetcher = authFetch) {
    return {
        list: () => f<ProfileList>(R),
        create: (profile: LaunchProfile, rev: number) => f<{ revision: number; profile: ProfileRow }>(R, { method: 'POST', body: json({ profile, expected_revision: rev }) }),
        replace: (profile: LaunchProfile, rev: number) => f<{ revision: number; profile: ProfileRow }>(`${R}/${seg(profile.id)}`, { method: 'PUT', body: json({ profile, expected_revision: rev }) }),
        remove: (id: string) => f<{ revision: number; removed: string }>(`${R}/${seg(id)}`, { method: 'DELETE' }),
        setDefault: (id: string) => f<{ revision: number }>(`${R}/${seg(id)}/default`, { method: 'POST' }),
        setIcon: (id: string, icon: string | null) => f<{ revision: number; profile: ProfileRow }>(`${R}/${seg(id)}/icon`, { method: 'PUT', body: json({ icon }) }),
        usage: (id: string) => f<UsageResult>(`${R}/${seg(id)}/usage`),
        previewDraft: (profile: LaunchProfile, model: string | null) => f<Preview>(`${R}/preview`, { method: 'POST', body: json({ profile, model }) }),
        check: (id: string) => f<CheckResult>(`${R}/${seg(id)}/check`, { method: 'POST' }),
        move: (id: string, to: string) => f<{ moved: Record<string, number> }>(`${R}/${seg(id)}/move-references`, { method: 'POST', body: json({ to }) }),
        exportDoc: (id: string) => f<unknown>(`${R}/${seg(id)}/export`),
        importPreview: (document: unknown) => f<ImportPreview>(`${R}/import/preview`, { method: 'POST', body: json({ document }) }),
        importDoc: (document: unknown, sha: string, replace: boolean) =>
            f<{ revision: number; profile: ProfileRow }>(`${R}/import`, { method: 'POST', body: json({ document, confirm_sha256: sha, replace }) }),
        accounts: async (): Promise<AccountOption[]> => (await f<AccountOption[]>('/provider-ledger/accounts')).filter((a) => a.provider === 'claude'),
        computerLaunchers: (hostKey: string) => f<ComputerLaunchers>(`/launchers/computer/${seg(hostKey)}`),
        launchAccounts: () => f<RestartAccounts>('/launch/accounts'),
        connections: async (): Promise<ConnectionOption[]> => (await f<{ connections: ConnectionOption[] }>('/ai/connections')).connections ?? [],
        models: async (connectionId: string): Promise<ModelOption[]> => {
            const cached = await f<{ models: ModelOption[] }>(`/ai/connections/${seg(connectionId)}/models?cached_only=true`);
            if (cached.models?.length) return cached.models;
            return (await f<{ models: ModelOption[] }>(`/ai/connections/${seg(connectionId)}/models`)).models ?? [];
        },
    };
}

export type LaunchProfilesApi = ReturnType<typeof createLaunchProfilesApi>;
