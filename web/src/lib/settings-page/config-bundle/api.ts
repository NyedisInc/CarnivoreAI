import { ApiError, authFetch } from '../../../opscenter/api/auth.svelte';

export type Fetcher = typeof authFetch;

export type ImportMode = 'merge' | 'replace';

export interface ChangeLine {
    readonly path: string;
    readonly kind: 'added' | 'changed' | 'removed';
    readonly before: string | null;
    readonly after: string | null;
}

export interface CommandPart {
    readonly kind: string;
    readonly text: string;
}

export interface AgentCommands {
    readonly id: string;
    readonly family: string | null;
    readonly label: string | null;
    readonly parts: readonly CommandPart[];
}

export interface ProfileCommands {
    readonly id: string;
    readonly label: string;
    readonly harness: string;
    readonly parts: readonly CommandPart[];
}

export const SETTING_SECTIONS = ['workspace', 'browser', 'provider_accounts', 'common_slash_commands', 'template_path'] as const;

export type SettingSection = (typeof SETTING_SECTIONS)[number];

export type SettingKind = 'env' | 'shell' | 'editor' | 'executable' | 'account_dir' | 'slash' | 'template';

export interface SettingCommands {
    readonly id: string;
    readonly kind: SettingKind;
    readonly label: string;
    readonly parts: readonly CommandPart[];
}

export interface SettingBlock {
    readonly sha256: string;
    readonly rows: readonly SettingCommands[];
}

export interface ImportAnswerCore {
    readonly status: 'preview' | 'applied' | 'unchanged';
    readonly dry_run: boolean;
    readonly mode: ImportMode;
    readonly changes: readonly ChangeLine[];
    readonly counts: { readonly added: number; readonly changed: number; readonly removed: number };
    readonly truncated: boolean;
    readonly stripped: readonly string[];
    readonly ignored: readonly string[];
    readonly backup: string | null;
    readonly source: { readonly source_host: string; readonly from_other_host: boolean; readonly app_version: string };
    readonly contains_commands?: boolean;
    readonly kept?: number;
    readonly agents?: { readonly sha256: string; readonly wrappers: readonly AgentCommands[] };
    readonly launch_profiles?: { readonly sha256: string; readonly profiles: readonly ProfileCommands[] };
}

export type ImportAnswer = ImportAnswerCore & { readonly [S in SettingSection]?: SettingBlock };

export interface CommandRow {
    readonly key: string;
    readonly kind: 'agent' | 'profile' | SettingKind;
    readonly id: string;
    readonly name: string;
    readonly parts: readonly CommandPart[];
}

const HIDDEN_CHARACTERS = /(?![\n\t])[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\u{FE00}-\u{FE0F}\u{E0100}-\u{E01EF}]/gu;

export function visibleCommand(text: string): string {
    return text.replace(HIDDEN_CHARACTERS, (ch) => `\\u{${ch.codePointAt(0)!.toString(16)}}`);
}

export type ImportConfirm = {
    readonly confirm_agents_sha256?: string;
    readonly confirm_launch_profiles_sha256?: string;
} & { readonly [S in SettingSection as `confirm_${S}_sha256`]?: string };

export function commandRows(answer: ImportAnswer): CommandRow[] {
    const agents = (answer.agents?.wrappers ?? []).map(
        (w, index): CommandRow => ({ key: `agents:${index}`, kind: 'agent', id: w.id, name: w.label || w.id, parts: w.parts }),
    );
    const profiles = (answer.launch_profiles?.profiles ?? []).map(
        (p, index): CommandRow => ({ key: `launch_profiles:${index}`, kind: 'profile', id: p.id, name: p.label || p.id, parts: p.parts }),
    );
    const settings = SETTING_SECTIONS.flatMap((section) =>
        (answer[section]?.rows ?? []).map(
            (w, index): CommandRow => ({ key: `${section}:${index}`, kind: w.kind, id: w.id, name: w.label || w.id, parts: w.parts }),
        ),
    );
    return [...agents, ...profiles, ...settings];
}

export function confirmFor(answer: ImportAnswer): ImportConfirm {
    return {
        ...(answer.agents ? { confirm_agents_sha256: answer.agents.sha256 } : {}),
        ...(answer.launch_profiles ? { confirm_launch_profiles_sha256: answer.launch_profiles.sha256 } : {}),
        ...Object.fromEntries(
            SETTING_SECTIONS.flatMap((section) => {
                const block = answer[section];
                return block ? [[`confirm_${section}_sha256`, block.sha256]] : [];
            }),
        ),
    };
}

export function isConsentStale(error: unknown): boolean {
    return error instanceof ApiError && error.status === 409;
}

export class BundleFileError extends Error {}

export function fetchBundle(fetcher: Fetcher = authFetch): Promise<Record<string, unknown>> {
    return fetcher<Record<string, unknown>>('/config/export');
}

export function sendImport(
    bundle: Record<string, unknown>,
    mode: ImportMode,
    dryRun: boolean,
    fetcher: Fetcher = authFetch,
    confirm: ImportConfirm = {},
): Promise<ImportAnswer> {
    return fetcher<ImportAnswer>('/config/import', {
        method: 'POST',
        body: JSON.stringify({ bundle, mode, dry_run: dryRun, ...confirm }),
    });
}

export function parseBundleText(text: string): Record<string, unknown> {
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        throw new BundleFileError('not json');
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new BundleFileError('not an object');
    return parsed as Record<string, unknown>;
}

export function bundleFilename(bundle: Record<string, unknown>): string {
    const stamp = typeof bundle.exported_at === 'string' ? bundle.exported_at.slice(0, 10).replaceAll('-', '') : '';
    return `carnivore-config-${stamp || 'export'}.json`;
}
