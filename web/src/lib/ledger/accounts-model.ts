import type { Translate } from '../sessions/types';
import { LEDGER_KEYS } from './ledger-model';

export type ProviderKind = 'claude' | 'codex';

export const DEFAULT_CLAUDE_CONFIG_DIR = '~/.claude';

export const DEFAULT_CODEX_HOME = '~/.codex';

export interface AccountDraft {
    name: string;
    provider: ProviderKind;
    path: string;
    managed: boolean;
    color: string | null;
}

export interface AccountBody {
    name: string;
    provider: ProviderKind;
    managed: boolean;
    color: string | null;
    short_name?: string;
    claude_config_dir?: string;
    codex_home?: string;
}

export interface StoredAccount {
    id: string;
    name?: string | null;
    provider?: string | null;
    claude_config_dir?: string | null;
    codex_home?: string | null;
    managed?: boolean | null;
    color?: string | null;
    short_name?: string | null;
}

const NOT_SLUG_CHARACTER = /[^a-z0-9]+/g;
const EDGE_DASHES = /^-+|-+$/g;

export function slugFromName(name: string): string {
    if (typeof name !== 'string') return '';
    return name.toLowerCase().replace(NOT_SLUG_CHARACTER, '-').replace(EDGE_DASHES, '');
}

export function pathFieldFor(provider: ProviderKind): 'claude_config_dir' | 'codex_home' {
    return provider === 'codex' ? 'codex_home' : 'claude_config_dir';
}

export function pathDefaultFor(provider: ProviderKind): string {
    return provider === 'codex' ? DEFAULT_CODEX_HOME : DEFAULT_CLAUDE_CONFIG_DIR;
}

export function pathLabelKey(provider: ProviderKind): string {
    return provider === 'codex' ? LEDGER_KEYS.editorCodexHomeLabel : LEDGER_KEYS.editorClaudeDirLabel;
}

export function pathHelpKey(provider: ProviderKind): string {
    return provider === 'codex' ? LEDGER_KEYS.editorCodexHomeHelp : LEDGER_KEYS.editorClaudeDirHelp;
}

export function accountBody(draft: AccountDraft): AccountBody {
    const body: AccountBody = {
        name: draft.name.trim(),
        provider: draft.provider,
        managed: draft.managed,
        color: draft.color,
    };
    if (draft.managed) return body;
    body.claude_config_dir = DEFAULT_CLAUDE_CONFIG_DIR;
    body.codex_home = DEFAULT_CODEX_HOME;
    body[pathFieldFor(draft.provider)] = draft.path.trim();
    return body;
}

export interface AccountEdit {
    name: string;
    color: string | null;
    short_name?: string;
}

export function storedAccountBody(
    stored: StoredAccount,
    edit: AccountEdit,
): AccountBody | null {
    const name = typeof edit.name === 'string' ? edit.name.trim() : '';
    const color = edit.color;
    const provider = stored.provider === 'codex' ? 'codex' : stored.provider;
    if (!name || (provider !== 'claude' && provider !== 'codex')) return null;
    const managed = stored.managed === true;
    const body: AccountBody = { name, provider, managed, color };
    // and an empty string
    if (typeof edit.short_name === 'string') body.short_name = edit.short_name.trim();
    if (managed) return body;
    const claudeDir = stored.claude_config_dir;
    const codexHome = stored.codex_home;
    if (typeof claudeDir !== 'string' || typeof codexHome !== 'string') return null;
    body.claude_config_dir = claudeDir;
    body.codex_home = codexHome;
    return body;
}

/* could not be read */
export function draftRefusal(
    draft: AccountDraft,
    taken: readonly string[] | null,
    t: Translate,
): string | null {
    if (!draft.name.trim()) return t(LEDGER_KEYS.editorNameBlank);
    const id = slugFromName(draft.name);
    if (!id) return t(LEDGER_KEYS.editorIdBlank);
    if (!draft.managed && !draft.path.trim()) return t(LEDGER_KEYS.editorPathBlank);
    if (taken !== null && taken.includes(id)) return t(LEDGER_KEYS.editorIdTaken, { id });
    return null;
}

interface ValidationEntry {
    loc?: unknown;
    msg?: unknown;
}

function fieldOf(loc: unknown): string {
    if (!Array.isArray(loc)) return '';
    const segments = loc
        .filter((part) => typeof part === 'string' || typeof part === 'number')
        .map((part) => String(part))
        .filter((part) => part !== 'body' && part !== 'path' && part !== 'query');
    return segments.at(-1) ?? '';
}

/* a network failure name must not be empty */
export function refusalText(error: unknown, t: Translate): string {
    const detail = (error as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    const listed = validationText(detail, t);
    if (listed) return listed;
    if (detail && typeof detail === 'object') {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === 'string' && message.trim()) return message;
        const nested = (detail as { detail?: unknown }).detail;
        if (typeof nested === 'string' && nested.trim()) return nested;
        const nestedList = validationText(nested, t);
        if (nestedList) return nestedList;
    }
    if (error instanceof Error && error.message) return error.message;
    return String(error);
}

function validationText(value: unknown, t: Translate): string {
    if (!Array.isArray(value)) return '';
    const lines = (value as ValidationEntry[])
        .map((entry) => {
            const msg = typeof entry?.msg === 'string' ? entry.msg : '';
            if (!msg) return '';
            const field = fieldOf(entry?.loc);
            return field ? t(LEDGER_KEYS.editorFieldRefusal, { field, detail: msg }) : msg;
        })
        .filter((line) => line !== '');
    return lines.length ? lines.join('; ') : '';
}

export function storedAccounts(rows: unknown): StoredAccount[] | null {
    if (!Array.isArray(rows)) return null;
    return rows.filter((row): row is StoredAccount => {
        const id = (row as StoredAccount | null)?.id;
        return typeof id === 'string' && id !== '';
    });
}
