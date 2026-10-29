<script lang="ts">
  import LedgerAddButton from '../../lib/ledger/LedgerAddButton.svelte';
  import Page from '../../opscenter/ui/Page.svelte';
  import { MANAGER_KEYS } from '../../lib/manager-frame/manager-model';
  import { LEDGER_KEYS } from '../../lib/ledger/ledger-model';
  import LedgerTotal from '../../lib/ledger/LedgerTotal.svelte';
  import LedgerCards from '../../lib/ledger/LedgerCards.svelte';
  import type { LedgerAccount } from '../../lib/ledger/ledger-model';
  import { t } from '../../lib/i18n/index.svelte';

  const now = Date.parse('2026-09-25T18:00:00Z');
  const soon = (hours: number): string => new Date(now + hours * 3600_000).toISOString();

  const accounts: LedgerAccount[] = [
    {
      id: 'personal',
      name: 'personal',
      provider: 'claude',
      plan: 'max',
      identity: 'someone@example.com',
      credential_state: 'ok',
      fetched_at: soon(-0.05),
      color: '#4acf93',
      windows: [
        { kind: 'five_hour', label: '5h', used_pct: 42, window_seconds: 18000, resets_at: soon(2.2) },
        { kind: 'seven_day', label: '7d', used_pct: 71, window_seconds: 604800, resets_at: soon(80) },
      ],
    },
    {
      id: 'work',
      name: 'work',
      provider: 'codex',
      plan: 'pro',
      identity: null,
      credential_state: 'expired',
      fetched_at: null,
      error: 'the server answered 502',
      windows: [{ kind: 'primary', label: '5h', used_pct: 96, window_seconds: 18000, resets_at: soon(0.4) }],
    },
  ];
</script>

{#snippet pageActions()}
  <LedgerAddButton adding={false} onAdd={() => {}} {t} />
{/snippet}

<Page
  embedded
  class="pledger"
  title={t(LEDGER_KEYS.screenTitle)}
  count={t(LEDGER_KEYS.totalAccounts, { count: accounts.length })}
  onClose={() => {}}
  closeLabel={t(MANAGER_KEYS.close)}
  actions={pageActions}
>
  <div class="oc-page__main oc-page__main--stack">
    <LedgerTotal
      total={{ accounts: 2, windows: [{ kind: 'five_hour', label: '5h', used_pct: 69, accounts: 2, resets_at: soon(2.2) }] }}
      {now}
      {t}
    />
    <LedgerCards {accounts} {now} {t} />
  </div>
</Page>
