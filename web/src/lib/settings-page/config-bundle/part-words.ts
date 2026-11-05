import type { Translate } from '../../sessions/types';
import { visibleCommand, type CommandPart } from './api';

const LABEL_KEYS: Readonly<Record<string, string>> = {
    harness: 'settings.configbundle.commands.part.harness',
    permissions: 'settings.configbundle.commands.part.permissions',
    endpoint: 'settings.configbundle.commands.part.endpoint',
    account: 'settings.configbundle.commands.part.account',
    default: 'settings.configbundle.commands.part.default',
    resume_command: 'settings.configbundle.commands.part.resume_command',
};

const VALUE_KEYS: Readonly<Record<string, string>> = {
    'permissions:harness_default': 'launch_profiles.posture.harness_default',
    'permissions:ask': 'launch_profiles.posture.ask',
    'permissions:accept_edits': 'launch_profiles.posture.accept_edits',
    'permissions:skip_all': 'launch_profiles.posture.skip_all',
    'endpoint:native': 'launch_profiles.editor.endpoint_native',
    'endpoint:connection': 'settings.configbundle.commands.value.endpoint_connection',
    'account:follow_active': 'launch_profiles.list.follow',
    'account:pinned': 'settings.configbundle.commands.value.account_pinned',
    'default:kept': 'settings.configbundle.commands.value.default_kept',
};

export interface PartView {
    readonly label: string;
    readonly words: string | null;
    readonly text: string;
    readonly warning: string | null;
    readonly tone: 'danger' | 'unknown' | null;
    readonly was: string | null;
}

function valueWords(kind: string, value: string, t: Translate): string {
    const key = VALUE_KEYS[`${kind}:${value}`];
    return key ? t(key) : visibleCommand(value);
}

function wasLine(part: CommandPart, t: Translate): string | null {
    if (part.was === undefined) return null;
    if (part.was === null) return t('settings.configbundle.commands.was_unset');
    if (part.value === undefined) return t('settings.configbundle.commands.was', { value: visibleCommand(part.was) });
    const detail = part.was_text ? ` ${visibleCommand(part.was_text)}` : '';
    return t('settings.configbundle.commands.was', { value: `${valueWords(part.kind, part.was, t)}${detail}` });
}

export function describePart(part: CommandPart, t: Translate): PartView {
    const labelKey = LABEL_KEYS[part.kind];
    const warningKey = part.tone === 'unknown'
        ? 'settings.configbundle.commands.flags_unknown'
        : part.kind === 'permissions' ? 'settings.configbundle.commands.skip_all' : 'settings.configbundle.commands.flags_danger';
    return {
        label: labelKey ? t(labelKey) : part.kind,
        words: part.value === undefined ? null : valueWords(part.kind, part.value, t),
        text: visibleCommand(part.text),
        warning: part.tone === undefined ? null : t(warningKey),
        tone: part.tone ?? null,
        was: wasLine(part, t),
    };
}
