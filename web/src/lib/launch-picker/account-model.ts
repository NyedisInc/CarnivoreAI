import type { AccountChoice, RestartAccounts } from './account-types';
import type { PickerRow } from './picker-model';

export interface AccountAnswer { accountId: string; pinned: boolean }

export function appliesTo(row: PickerRow | undefined, answer: RestartAccounts | null): boolean {
    if (!row || !answer || answer.options.length === 0) return false;
    const family = row.data?.family;
    if (family !== undefined) return (family === '' || family === 'claude' || family === 'codex') && row.followsActive !== false;
    return (row.harness === 'claude' || row.harness === 'codex') && row.followsActive === true;
}

export function viewFor(row: PickerRow | undefined, answer: RestartAccounts | null): RestartAccounts | null {
    if (!answer) return null;
    const provider = (row?.data?.family || row?.harness) === 'codex' ? 'codex' : 'claude';
    const options = answer.options.filter((o) => (o.provider ?? 'claude') === provider);
    const byProvider = answer.selected_by_provider;
    return { ...answer, options, selected_id: byProvider ? (byProvider[provider] ?? null) : answer.selected_id };
}

export function startAccountId(answer: RestartAccounts): string {
    return answer.selected_id ?? answer.options[0]?.id ?? '';
}

export function summaryOf(answer: RestartAccounts): AccountChoice | undefined {
    const hit = answer.options.find((o) => o.id === answer.selected_id);
    return answer.pinned || answer.active_id === undefined || answer.active_id === answer.selected_id ? hit : undefined;
}

export function tagKeys(option: AccountChoice, answer: RestartAccounts): string[] {
    const keys: string[] = [];
    if (answer.pinned) {
        if (option.id === answer.selected_id) keys.push('launch_picker.account.tag.saved');
    } else if (option.id === (answer.active_id === undefined ? answer.selected_id : answer.active_id)) keys.push('launch_picker.account.tag.active');
    if (option.is_current) keys.push('launch_picker.account.tag.current');
    return keys;
}

export function answerOf(show: boolean, expanded: boolean, accountId: string, pinned: boolean): AccountAnswer | null {
    return show && expanded && accountId ? { accountId, pinned } : null;
}
