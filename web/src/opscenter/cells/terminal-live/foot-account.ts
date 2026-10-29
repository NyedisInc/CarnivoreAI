/* active account */

export interface FootAccount {
  name: string;
  mismatch: boolean;
}

export interface FootAccountRow {
  id: string;
  name: string;
  short_name?: string | null;
}

const FAMILY_PROVIDER: Record<string, string> = { claude: 'claude', codex: 'codex' };

/* active account */
export function footAccount(
  family: string | null | undefined,
  accountId: string | null | undefined,
  accounts: readonly FootAccountRow[] | undefined,
  active: readonly { provider: string; account_id: string | null }[] | undefined,
): FootAccount | null {
  if (!accountId) return null;
  const row = accounts?.find((a) => a.id === accountId);
  if (!row) return null;
  const provider = FAMILY_PROVIDER[family ?? ''];
  const activeId = provider ? (active?.find((a) => a.provider === provider)?.account_id ?? null) : null;
  return { name: row.short_name || row.name, mismatch: !!activeId && activeId !== accountId };
}
