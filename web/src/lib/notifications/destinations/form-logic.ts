import { ApiError } from '../../../opscenter/api/auth.svelte';
import type { Translate } from '../../sessions/types';
import type { PickItem } from '../../byoai/picker-logic';
import type { Destination, DestinationBody, Kind, KindField } from './api';

export interface Draft {
    kind: string;
    name: string;
    enabled: boolean;
    config: Record<string, string>;
    secrets: Record<string, string>;
    allowPrivate: boolean;
    allowPlainHttp: boolean;
}

export const kindOf = (kinds: readonly Kind[], id: string): Kind | undefined => kinds.find((k) => k.id === id);

export const addableKinds = (kinds: readonly Kind[]): Kind[] => kinds.filter((k) => !k.virtual);

export function isPluginKind(kind: Pick<Kind, 'id' | 'plugin_id'>): boolean {
    return Boolean(kind.plugin_id) || kind.id.startsWith('plugin:');
}

export function kindLabel(kind: Kind, t: Translate): string {
    const translated = t(kind.label_key);
    if (translated !== kind.label_key) return translated;
    return kind.label?.trim() || kind.id;
}

export function fieldLabel(field: KindField, t: Translate): string {
    const key = `settings.notify.field.${field.name}`;
    const translated = t(key);
    if (translated !== key) return translated;
    return field.label?.trim() || field.name.replace(/_/g, ' ');
}

const KIND_GROUPS: ReadonlyArray<readonly [string, readonly string[]]> = [
    ['chat', ['slack', 'discord', 'teams', 'telegram']], ['push', ['ntfy', 'pushover']], ['incident', ['pagerduty']],
    ['sms', ['sns', 'twilio']], ['other', ['email', 'webhook']], ['plugins', []],
];

export function kindItems(kinds: readonly Kind[], t: Translate): PickItem[] {
    const pluginsIdx = KIND_GROUPS.findIndex(([name]) => name === 'plugins');
    const otherIdx = KIND_GROUPS.findIndex(([name]) => name === 'other');
    const group = (k: Kind): number => {
        if (isPluginKind(k)) return pluginsIdx;
        const at = KIND_GROUPS.findIndex(([, ids]) => ids.includes(k.id));
        return at < 0 ? otherIdx : at;
    };
    return kinds
        .map((k) => ({
            id: k.id,
            text: kindLabel(k, t),
            name: isPluginKind(k) ? (k.plugin_id ?? '') : '',
            vendor: t(`settings.notify.kind.group.${KIND_GROUPS[group(k)]![0]}`),
            detail: '',
            flags: [],
            preset: k.id,
        }))
        .sort((a, b) => {
            const ka = kinds.find((x) => x.id === a.id)!;
            const kb = kinds.find((x) => x.id === b.id)!;
            return group(ka) - group(kb);
        });
}

export function initialDraft(kind: Kind, saved: Destination | null): Draft {
    const config: Record<string, string> = {};
    for (const f of kind.public_fields) config[f.name] = saved?.config[f.name] === undefined || saved.config[f.name] === null ? '' : String(saved.config[f.name]);
    return { kind: kind.id, name: saved?.name ?? '', enabled: saved?.enabled ?? true, config, secrets: {}, allowPrivate: saved?.allow_private === true,
        allowPlainHttp: saved?.allow_private === true && saved?.allow_plain_http === true };
}

export const splitList = (text: string): string[] => text.split(/[\n,]/).map((s) => s.trim()).filter((s) => s.length > 0);

const typed = (value: unknown): string => String(value ?? '').trim();

function wire(field: KindField, raw: unknown): unknown {
    const text = typed(raw);
    if (field.type === 'int') return Number(text);
    if (field.type === 'list') return splitList(text);
    return text;
}

function configBody(kind: Kind, draft: Draft): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const f of kind.public_fields) {
        if (typed(draft.config[f.name]) !== '') out[f.name] = wire(f, draft.config[f.name]);
    }
    return out;
}

export function secretsBody(kind: Kind, draft: Draft): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const f of kind.secret_fields) {
        if (typed(draft.secrets[f.name]) !== '') out[f.name] = wire(f, draft.secrets[f.name]);
    }
    return out;
}

export function complete(kind: Kind, draft: Draft, saved: Destination | null): boolean {
    if (draft.name.trim() === '') return false;
    if (kind.public_fields.some((f) => f.required && typed(draft.config[f.name]) === '')) return false;
    return !kind.secret_fields.some((f) => f.required && typed(draft.secrets[f.name]) === '' && !saved?.secrets[f.name]?.set);
}

export function createBody(kind: Kind, draft: Draft, scope: 'global' | 'local'): DestinationBody {
    const body: DestinationBody = { kind: kind.id, name: draft.name.trim(), enabled: draft.enabled, scope, config: configBody(kind, draft), secrets: secretsBody(kind, draft) };
    if (kind.allow_private) {
        body.allow_private = draft.allowPrivate;
        body.allow_plain_http = draft.allowPrivate && draft.allowPlainHttp;
    }
    return body;
}

export function patchBody(kind: Kind, draft: Draft, saved: Destination): DestinationBody {
    const body: DestinationBody = { name: draft.name.trim(), enabled: draft.enabled, config: configBody(kind, draft) };
    const secrets = secretsBody(kind, draft);
    if (Object.keys(secrets).length > 0) body.secrets = secrets;
    if (kind.allow_private) {
        body.allow_private = draft.allowPrivate;
        body.allow_plain_http = draft.allowPrivate && draft.allowPlainHttp;
    }
    if (saved.pinned) body.scope = 'local';
    return body;
}

export const failureKey = (failure: string): string => `settings.notify.dest.failure.${failure}`;

export const fieldProblemKey = (code: string): string => `settings.notify.dest.problem.${code}`;

const SAVE_CODES: readonly string[] = ['https_required', 'private_address', 'not_supported', 'plain_http_public', 'requires_allow_private'];

export function saveProblem(error: unknown, t: (key: string) => string): string | null {
    if (!(error instanceof ApiError) || error.status !== 422) return null;
    const detail = (error.payload as { detail?: { fields?: unknown } } | null)?.detail;
    const fields = detail && typeof detail === 'object' ? detail.fields : null;
    if (!fields || typeof fields !== 'object') return null;
    const code = Object.values(fields as Record<string, unknown>).find((c): c is string => typeof c === 'string' && SAVE_CODES.includes(c));
    return code ? t(fieldProblemKey(code)) : null;
}
