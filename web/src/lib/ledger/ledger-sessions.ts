import type { SessionInfo } from '../../opscenter/api/types';

export type ProviderSession = Pick<SessionInfo, 'session' | 'tmux_session' | 'label'> &
    Partial<SessionInfo>;

export interface SessionsByAccount {
    byAccount: Map<string, ProviderSession[]>;
    unknown: ProviderSession[];
}

export function groupSessionsByAccount(
    rows: readonly ProviderSession[],
    accountIds: readonly string[],
): SessionsByAccount {
    const byAccount = new Map<string, ProviderSession[]>();
    for (const id of accountIds) byAccount.set(id, []);
    const unknown: ProviderSession[] = [];
    for (const row of rows) {
        const id = row.account_id;
        const list = typeof id === 'string' ? byAccount.get(id) : undefined;
        if (list) list.push(row);
        else unknown.push(row);
    }
    return { byAccount, unknown };
}

export function sessionTitle(row: ProviderSession): string {
    return row.label ?? row.tmux_session ?? row.session.id;
}
