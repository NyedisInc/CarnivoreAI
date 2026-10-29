import type { ConnectionOption, Harness, LaunchProfile, Posture } from './api';

export const STRUCTURED: readonly Harness[] = ['claude', 'codex', 'shell'];

export const POSTURES_BY_HARNESS: Readonly<Record<string, readonly Posture[]>> = {
    claude: ['harness_default', 'ask', 'accept_edits', 'skip_all'],
    codex: ['harness_default', 'ask', 'skip_all'],
    shell: ['harness_default'],
};

export const ALL_POSTURES: readonly Posture[] = ['harness_default', 'ask', 'accept_edits', 'skip_all'];

export function postureSupported(harness: Harness, posture: Posture): boolean {
    return (POSTURES_BY_HARNESS[harness] ?? ['harness_default']).includes(posture);
}

export interface FormState {
    id: string;
    isNew: boolean;
    harness: Harness;
    label: string;
    icon: string | null;
    description: string;
    default: boolean;
    accountMode: 'follow_active' | 'pinned';
    accountId: string;
    endpointMode: 'native' | 'connection';
    connectionId: string;
    modelMode: 'default' | 'fixed' | 'ask';
    modelValue: string;
    permissions: Posture;
    flagsText: string;
    env: { name: string; value: string }[];
    secrets: { name: string; keychain_ref: string }[];
    shellProfile: boolean;
    beforeLaunch: string;
    expert: boolean;
    script: string;
    entry: string;
    ackNoArgs: boolean;
}

export function blankForm(): FormState {
    return {
        id: '', isNew: true, harness: 'claude', label: '', icon: null, description: '', default: false,
        accountMode: 'follow_active', accountId: '', endpointMode: 'native', connectionId: '',
        modelMode: 'default', modelValue: '', permissions: 'harness_default', flagsText: '', env: [], secrets: [],
        shellProfile: true, beforeLaunch: '', expert: false, script: '', entry: '', ackNoArgs: false,
    };
}

export function profileToForm(p: LaunchProfile): FormState {
    return {
        id: p.id, isNew: false, harness: p.harness, label: p.label, icon: p.icon, description: p.description ?? '',
        default: p.default, accountMode: p.account.mode, accountId: p.account.account_id ?? '',
        endpointMode: p.endpoint.mode, connectionId: p.endpoint.connection_id ?? '',
        modelMode: p.model.mode, modelValue: p.model.value ?? '', permissions: p.permissions,
        flagsText: p.flags.join('\n'), env: p.env.map((r) => ({ ...r })), secrets: p.secrets.map((r) => ({ ...r })),
        shellProfile: p.shell_profile, beforeLaunch: p.before_launch ?? '',
        expert: p.custom_command !== null, script: p.custom_command?.script ?? '', entry: p.custom_command?.entry ?? '',
        ackNoArgs: p.custom_command_ack_no_args,
    };
}

export function slugFromLabel(label: string): string {
    return label.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 64);
}

export function uniqueId(base: string, taken: ReadonlySet<string>): string {
    if (!base) return base;
    if (!taken.has(base)) return base;
    for (let n = 2; n < 1000; n += 1) {
        const next = `${base.slice(0, 60)}-${n}`;
        if (!taken.has(next)) return next;
    }
    return base;
}

export function lintMissingArgs(script: string, entry: string): boolean {
    return script.trim() !== '' && !script.includes('"$@"') && entry.trim() === '';
}

export function parseFlags(text: string): string[] {
    return text.split('\n').map((l) => l.trim()).filter((l) => l !== '');
}

export function formToProfile(f: FormState): LaunchProfile {
    const structured = STRUCTURED.includes(f.harness);
    const custom = f.expert && f.script.trim() !== '';
    return {
        id: f.id.trim(),
        harness: f.harness,
        label: f.label.trim(),
        icon: f.icon,
        description: f.description.trim() || null,
        default: f.default,
        account: f.harness === 'claude' && f.accountMode === 'pinned'
            ? { mode: 'pinned', account_id: f.accountId || null }
            : { mode: 'follow_active', account_id: null },
        endpoint: structured && f.harness !== 'shell' && f.endpointMode === 'connection'
            ? { mode: 'connection', connection_id: f.connectionId || null }
            : { mode: 'native', connection_id: null },
        model: f.modelMode === 'fixed' && f.harness !== 'shell'
            ? { mode: 'fixed', value: f.modelValue.trim() || null }
            : { mode: f.modelMode === 'ask' ? 'ask' : 'default', value: null },
        permissions: postureSupported(f.harness, f.permissions) ? f.permissions : 'harness_default',
        flags: structured ? parseFlags(f.flagsText) : [],
        env: f.env.filter((r) => r.name.trim() !== '').map((r) => ({ name: r.name.trim(), value: r.value })),
        secrets: f.secrets.filter((r) => r.name.trim() !== '').map((r) => ({ name: r.name.trim(), keychain_ref: r.keychain_ref })),
        shell_profile: f.shellProfile,
        before_launch: f.beforeLaunch.trim() || null,
        custom_command: custom ? { script: f.script, entry: f.entry.trim() || null } : null,
        custom_command_ack_no_args: custom ? f.ackNoArgs : false,
    };
}

export interface Template {
    id: 'claude_subscription' | 'claude_openrouter' | 'claude_lmstudio' | 'codex_yolo' | 'shell';
    preset: string | null;
}

export const TEMPLATES: readonly Template[] = [
    { id: 'claude_subscription', preset: null },
    { id: 'claude_openrouter', preset: 'openrouter' },
    { id: 'claude_lmstudio', preset: 'lmstudio' },
    { id: 'codex_yolo', preset: null },
    { id: 'shell', preset: null },
];

export function templateForm(t: Template, label: string, connections: readonly ConnectionOption[]): FormState {
    const base = { ...blankForm(), label, id: slugFromLabel(label) };
    const found = t.preset ? connections.find((c) => c.preset === t.preset && c.enabled) : undefined;
    switch (t.id) {
        case 'claude_openrouter':
        case 'claude_lmstudio':
            return { ...base, endpointMode: 'connection', connectionId: found?.id ?? '', modelMode: 'ask' };
        case 'codex_yolo':
            return { ...base, harness: 'codex', permissions: 'skip_all' };
        case 'shell':
            return { ...base, harness: 'shell', shellProfile: false };
        default:
            return base;
    }
}
