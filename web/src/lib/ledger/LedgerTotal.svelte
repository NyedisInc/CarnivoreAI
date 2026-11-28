<!-- cannot be read -->
<script lang="ts">
    import type { AccountUsage } from '../../opscenter/api/types';
    import Card from '../base/Card.svelte';
    import { longWindow } from '../ledger-drawer/recommend';
    import type { Translate } from '../sessions/types';
    import LedgerUsageCell from './LedgerUsageCell.svelte';
    import { LEDGER_KEYS, type LedgerTotal, type LedgerTotalWindow } from './ledger-model';

    interface Props {
        total: LedgerTotal;
        now: number;
        t: Translate;
    }

    const { total, now, t }: Props = $props();

    const providerWindows = $derived.by((): LedgerTotalWindow[] => {
        const byProvider = new Map<string, LedgerTotalWindow[]>();
        for (const w of total.windows ?? []) {
            const key = w.provider ?? '';
            const list = byProvider.get(key);
            if (list) list.push(w);
            else byProvider.set(key, [w]);
        }
        const out: LedgerTotalWindow[] = [];
        for (const windows of byProvider.values()) {
            const picked = longWindow({ windows } as unknown as AccountUsage) as LedgerTotalWindow | null;
            out.push(picked ?? windows[0]);
        }
        return out;
    });
</script>

<Card data-ledger="total" title={t(LEDGER_KEYS.totalLabel)} meta={t(LEDGER_KEYS.totalAccounts, { count: total.accounts ?? 0 })} headingLevel={2}>
    {#snippet children()}
        <LedgerUsageCell windows={providerWindows} {now} {t} />
    {/snippet}
</Card>
