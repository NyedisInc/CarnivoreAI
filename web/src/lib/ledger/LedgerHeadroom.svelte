
<script lang="ts">
    import StatTile from '../base/StatTile.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import {
        CONTEXT_SEGMENTS,
        WINDOW_SCALE_STOPS,
        filledSegments,
        scaleStepFor,
    } from '../../../../client/js/labels/usage-panel.js';
    import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
    import {
        LEDGER_KEYS,
        formatPercent,
        formatWindowLabel,
        rankByHeadroom,
        worstWindow,
        type LedgerAccount,
    } from './ledger-model';

    interface Props {
        accounts: readonly LedgerAccount[];
        t: Translate;
    }

    const { accounts, t }: Props = $props();

    const ranked = $derived(rankByHeadroom(accounts));
</script>

<ul class="ledger-headroom" aria-label={t(LEDGER_KEYS.headroomLabel)}>
    {#each ranked as account, index (account.id ?? index)}
        {@const worst = worstWindow(account)}
        {@const name = account.name ?? account.id}
        <li class="ledger-headroom__item" data-name={name}>
            <StatTile
                label={name}
                size="compact"
                mode="flat"
                figure={worst ? formatPercent(worst.pct, t) : t(LEDGER_KEYS.notMeasured)}
                kind={worst ? 'value' : 'note'}
                sub={worst ? formatWindowLabel(worst.window, t) : ''}
            >
                {#snippet icon()}
                    {#if account.color}<span class="ledger-headroom__swatch" style:--mark={account.color}></span>{/if}
                    {@html providerMark(account.provider, 14).svg}
                {/snippet}
                {#snippet foot()}
                    {#if worst}
                        <LimitGauge
                            segments={CONTEXT_SEGMENTS}
                            filled={filledSegments(worst.pct)}
                            scale={scaleStepFor(worst.pct, WINDOW_SCALE_STOPS)}
                            meterText={t(LEDGER_KEYS.meterLabel, { window: formatWindowLabel(worst.window, t) })}
                            height={4}
                        />
                    {/if}
                {/snippet}
            </StatTile>
        </li>
    {/each}
</ul>

<style>
    .ledger-headroom {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(min(100%, 148px), 1fr));
        gap: var(--oc-space-3);
        margin: 0;
        padding: 0;
        list-style: none;
    }

    .ledger-headroom__item {
        display: flex;
        min-width: 0;
    }

    .ledger-headroom__item > :global(.oc-stat-tile) {
        flex: 1 1 auto;
    }

    .ledger-headroom__swatch {
        display: inline-block;
        width: 10px;
        height: 10px;
        margin-right: var(--oc-space-1);
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-control);
        background: var(--mark);
    }
</style>
