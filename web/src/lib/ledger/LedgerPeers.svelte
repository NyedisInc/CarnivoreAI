<!-- did not answer -->
<script lang="ts">
    import Card from '../base/Card.svelte';
    import State from '../base/State.svelte';
    import type { Translate } from '../sessions/types';
    import LedgerUsageCell from './LedgerUsageCell.svelte';
    import { LEDGER_KEYS, type PeersLedger } from './ledger-model';

    interface Props {
        peers: PeersLedger;
        now: number;
        t: Translate;
    }

    const { peers, now, t }: Props = $props();
</script>

{#if (peers.peers?.length ?? 0) > 0 || (peers.peer_unavailable?.length ?? 0) > 0}
    <section class="ledger-peers" data-ledger-peers aria-label={t(LEDGER_KEYS.peerLabel)}>
        {#each peers.peer_unavailable ?? [] as down (down.host_label)}
            <State inline data-peer-unavailable title={t(LEDGER_KEYS.peerUnavailable, { machine: down.host_label })} />
        {/each}
        {#each peers.peers ?? [] as peer (peer.host_label)}
            <Card title={peer.host_label} meta={t(LEDGER_KEYS.totalAccounts, { count: peer.accounts.length })} headingLevel={2}>
                {#snippet children()}
                    {#each peer.accounts as account (account.name + account.provider)}
                        <div class="ledger-peers__row" data-peer-account>
                            <span class="ledger-peers__name">{account.name}</span>
                            <span class="ledger-peers__meta">{account.provider}{account.plan ? ` / ${account.plan}` : ''}</span>
                            {#if account.shared}
                                <span class="ledger-peers__shared" data-peer-shared>{t(LEDGER_KEYS.peerShared)}</span>
                            {:else}
                                <LedgerUsageCell windows={account.windows ?? []} {now} {t} />
                            {/if}
                        </div>
                    {/each}
                {/snippet}
            </Card>
        {/each}
    </section>
{/if}

<style>
  @layer components {
    .ledger-peers {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-4);
    }

    .ledger-peers__row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: var(--oc-space-1) var(--oc-space-3);
        padding-top: var(--oc-space-2);
        box-shadow: inset 0 var(--oc-border) 0 0 var(--oc-line-hairline);
    }

    .ledger-peers__row:first-child {
        padding-top: 0;
        box-shadow: none;
    }

    .ledger-peers__name {
        color: var(--oc-text-primary);
    }

    .ledger-peers__meta,
    .ledger-peers__shared {
        font-size: var(--oc-fs-body);
        color: var(--oc-text-secondary);
    }

    .ledger-peers__row > :global(*:nth-child(n + 3)) {
        grid-column: 1 / -1;
    }
  }
</style>
