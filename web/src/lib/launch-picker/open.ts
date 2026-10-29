import { mountPanel, unmountPanel } from '../mount';
import { openModal } from '../modal';
import { t as appT } from '../i18n/index.svelte';
import type { Translate } from '../sessions/types';
import LaunchChoiceHost from './LaunchChoiceHost.svelte';
import LaunchPickerModal from './LaunchPickerModal.svelte';
import type { LaunchProfilesApi } from '../launch-profiles-page/api';
import type { AccountAnswer } from './account-model';
import type { RestartAccounts } from './account-types';
import type { PickerRow } from './picker-model';

export interface PickerAnswer { profileId: string; profileLabel: string; model: string | null; account: AccountAnswer | null; farLauncher?: boolean }

export interface OpenOptions {
    title?: string;
    preselect?: string | null;
    projectDefault?: string | null;
    harness?: string | null;
    onlyHarnesses?: readonly string[] | null;
    onlyIds?: readonly string[] | null;
    lastModel?: string;
    accounts?: boolean;
    remote?: { key: string; label: string } | null;
    goLabel?: string | null;
}

export function openLaunchPicker(options: OpenOptions = {}, t: Translate = appT): Promise<PickerAnswer | null> {
    const title = options.title ?? t('launch_picker.title');
    return openModal<PickerAnswer, Record<string, unknown>>(LaunchPickerModal as never, { ...options, title, t });
}

export interface LaunchChoiceHandle {
    selected(): { value: string; data: Record<string, string>; disabled: boolean } | null;
    setEnabled(predicate: (data: Record<string, string>) => boolean): void;
    selectFirst(predicate: (row: PickerRow) => boolean): void;
    account(): AccountAnswer | null;
    focus(): void;
    destroy(): void;
}

export interface LaunchChoiceOptions {
    rows: PickerRow[];
    value?: string;
    label?: string;
    accounts?: RestartAccounts | null;
    api?: LaunchProfilesApi;
}

/* label: ' */
export function mountLaunchChoice(containerId: string, opts: LaunchChoiceOptions): LaunchChoiceHandle | null {
    const host = mountPanel(containerId, LaunchChoiceHost, { rows: opts.rows, value: opts.value ?? '', label: opts.label ?? '', accounts: opts.accounts ?? null, api: opts.api });
    if (!host) return null;
    const call = host as unknown as {
        selected: LaunchChoiceHandle['selected']; setEnabled: LaunchChoiceHandle['setEnabled']; selectFirst: LaunchChoiceHandle['selectFirst'];
        accountAnswer: LaunchChoiceHandle['account']; focus: LaunchChoiceHandle['focus'];
    };
    return {
        selected: () => call.selected(), setEnabled: (p) => call.setEnabled(p), selectFirst: (p) => call.selectFirst(p),
        account: () => call.accountAnswer(), focus: () => call.focus(), destroy: () => { unmountPanel(containerId); },
    };
}
