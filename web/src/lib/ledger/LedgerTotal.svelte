
<script lang="ts">
    import Card from '../base/Card.svelte';
    import type { Translate } from '../sessions/types';
    import LedgerUsageCell from './LedgerUsageCell.svelte';
    import { LEDGER_KEYS, type LedgerTotal } from './ledger-model';

    interface Props {
        total: LedgerTotal;
        now: number;
        t: Translate;
    }

    const { total, now, t }: Props = $props();
</script>

<Card data-ledger="total" title={t(LEDGER_KEYS.totalLabel)} meta={t(LEDGER_KEYS.totalAccounts, { count: total.accounts ?? 0 })} headingLevel={2}>
    {#snippet children()}
        <LedgerUsageCell windows={total.windows ?? []} {now} {t} />
    {/snippet}
</Card>
