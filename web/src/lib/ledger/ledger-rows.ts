import type { StoredAccount } from './accounts-model';
import type { LedgerAccount } from './ledger-model';

export const UNMEASURED_CREDENTIAL_STATE = 'unknown';

function placeholderRow(account: StoredAccount): LedgerAccount {
    return {
        id: account.id,
        name: typeof account.name === 'string' ? account.name : null,
        provider: typeof account.provider === 'string' ? account.provider : '',
        plan: null,
        identity: null,
        credential_state: UNMEASURED_CREDENTIAL_STATE,
        fetched_at: null,
        next_poll_at: null,
        error: null,
        windows: [],
        ...configuredFacts(account),
    };
}

function configuredFacts(account: StoredAccount): {
    color: string | null;
    managed: boolean;
} {
    return {
        color: typeof account.color === 'string' ? account.color : null,
        managed: account.managed === true,
    };
}

/* could not be read */
export function mergeConfiguredRows(
    configured: readonly StoredAccount[] | null,
    measured: readonly LedgerAccount[],
): LedgerAccount[] {
    if (configured === null) return [...measured];

    const byId = new Map<string, LedgerAccount>();
    for (const row of measured) {
        if (typeof row.id === 'string' && !byId.has(row.id)) byId.set(row.id, row);
    }

    const rows: LedgerAccount[] = [];
    const painted = new Set<string>();
    for (const account of configured) {
        const row = byId.get(account.id);
        rows.push(row ? { ...row, ...configuredFacts(account) } : placeholderRow(account));
        painted.add(account.id);
    }
    for (const row of measured) {
        if (typeof row.id === 'string' && painted.has(row.id)) continue;
        rows.push(row);
    }
    return rows;
}
