import type { Connection, CreateBody, ModelInfo, PatchBody, Preset } from './api';

export interface Draft {
    preset: string;
    label: string;
    baseUrl: string;
    options: Record<string, unknown>;
    enabled: boolean;
    key: string;
    clearKey: boolean;
}

export function originOf(url: string): string {
    try {
        const u = new URL(url.trim());
        const host = u.hostname.toLowerCase().replace(/\.+$/, '');
        return `${u.protocol.toLowerCase()}//${host}${u.port ? `:${u.port}` : ''}`;
    } catch {
        return '';
    }
}

export function hostOf(url: string): string {
    try {
        return new URL(url.trim()).host.toLowerCase();
    } catch {
        return '';
    }
}

export function defaultBaseUrl(preset: Preset, options: Readonly<Record<string, unknown>>): string {
    if (!preset.base_url.includes('{region}')) return preset.base_url;
    return preset.base_url.replace('{region}', String(options['region'] || 'us-east-1'));
}

export function dropsKey(connection: Connection | null, baseUrl: string, typedKey: string): boolean {
    if (!connection || !connection.has_key || !connection.key_host || typedKey.trim()) return false;
    const origin = originOf(baseUrl);
    return origin !== '' && origin !== connection.key_host;
}

export function initialDraft(preset: Preset, connection: Connection | null): Draft {
    if (connection) {
        return { preset: preset.id, label: connection.label, baseUrl: connection.base_url, options: { ...connection.options },
            enabled: connection.enabled, key: '', clearKey: false };
    }
    const options: Record<string, unknown> = {};
    for (const field of preset.fields) if (field.default !== null && field.default !== undefined) options[field.name] = field.default;
    if (preset.custom) options['capabilities'] = ['chat'];
    return { preset: preset.id, label: preset.label, baseUrl: defaultBaseUrl(preset, options), options, enabled: true, key: '', clearKey: false };
}

export const EXTRA_BODY_OPTION = 'extra_body';

export function speaksOpenAiChat(preset: Preset): boolean {
    return preset.kind !== 'cli' && (preset.capabilities['chat'] ?? []).includes('openai_chat');
}

export function extraBodyProblem(text: string): string | null {
    if (!text.trim()) return null;
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        return 'settings.ai.form.extra_body_not_json';
    }
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed) ? null : 'settings.ai.form.extra_body_not_object';
}

export function cleanOptions(preset: Preset, options: Readonly<Record<string, unknown>>): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const field of preset.fields) {
        const value = options[field.name];
        if (value === undefined || value === null || value === '') continue;
        if (field.name === 'auth_header' && options['auth'] !== 'custom-header') continue;
        out[field.name] = value;
    }
    const extra = options[EXTRA_BODY_OPTION];
    if (speaksOpenAiChat(preset) && typeof extra === 'string' && extra.trim()) out[EXTRA_BODY_OPTION] = extra.trim();
    return out;
}

export function patchFor(preset: Preset, saved: Connection, draft: Draft, revision: number): PatchBody {
    const body: PatchBody = { expected_revision: revision };
    if (draft.label.trim() !== saved.label) body.label = draft.label.trim();
    if (draft.baseUrl.trim() !== saved.base_url) body.base_url = draft.baseUrl.trim();
    const options = cleanOptions(preset, draft.options);
    if (JSON.stringify(options) !== JSON.stringify(saved.options)) body.options = options;
    if (draft.enabled !== saved.enabled) body.enabled = draft.enabled;
    if (draft.key.trim()) body.key = draft.key.trim();
    return body;
}

export function offeredCapabilities(preset: Preset, connection: Pick<Connection, 'options'>): string[] {
    const all = Object.keys(preset.capabilities);
    if (!preset.custom) return all;
    const ticked = connection.options['capabilities'];
    return all.filter((c) => Array.isArray(ticked) && ticked.includes(c));
}

const OUTPUT_FOR: Readonly<Record<string, string>> = { chat: 'text', agent: 'text', decide: 'text', image: 'image', video: 'video', audio: 'audio' };

export function modelsFor(models: readonly ModelInfo[], capability: string): ModelInfo[] {
    const need = OUTPUT_FOR[capability];
    return models.filter((m) => m.meta['enabled'] !== false && (m.capabilities.length === 0 || m.capabilities.includes(capability))
        && (!need || !m.outputs || m.outputs.length === 0 || m.outputs.includes(need)));
}

export function voicesOf(model: ModelInfo | undefined): string[] {
    const voices = model?.meta['voices'];
    if (!Array.isArray(voices)) return [];
    return voices.map((v) => (typeof v === 'string' ? v : String((v as { id?: unknown; name?: unknown }).id ?? (v as { name?: unknown }).name ?? ''))).filter(Boolean);
}

export const base64Bytes = (data: string): number => Math.floor((data.length * 3) / 4) - (data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0);

export function createFor(preset: Preset, draft: Draft, revision: number): CreateBody {
    const body: CreateBody = { preset: preset.id, label: draft.label.trim(), base_url: preset.kind === 'cli' ? '' : draft.baseUrl.trim(),
        options: cleanOptions(preset, draft.options), expected_revision: revision };
    if (draft.key.trim()) body.key = draft.key.trim();
    return body;
}

export const ledgerProviderOf = (preset: Preset): string => preset.id.replace(/_cli$/, '');

export function usesKey(preset: Preset, options: Readonly<Record<string, unknown>>): boolean {
    if (preset.kind === 'cli') return false;
    const style = preset.auth_choices.length > 0 && typeof options['auth'] === 'string' ? options['auth'] : preset.auth;
    return style !== 'none';
}
