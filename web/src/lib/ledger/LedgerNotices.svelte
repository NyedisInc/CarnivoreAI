
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import State from '../base/State.svelte';
    import InfoTip from '../info-tip/InfoTip.svelte';
    import { LEDGER_KEYS, formatAge, type LedgerLoop } from './ledger-model';

    interface Props {
        loop: LedgerLoop | null;
        failure: string | null;
        loading: boolean;
        isEmpty: boolean;
        now: number;
        t: Translate;
    }

    const { loop, failure, loading, isEmpty, now, t }: Props = $props();
</script>


<div class="ledger-keepalive">
    <span class="ledger-keepalive__label">{t(LEDGER_KEYS.keepaliveLabel)}</span>
    <InfoTip text={t(LEDGER_KEYS.keepaliveInfo)} label={t(LEDGER_KEYS.keepaliveLabel)} />
</div>


{#if loop && loop.alive !== true}
    <State kind="warn" inline role="status" data-ledger="loop"
        title={t(LEDGER_KEYS.loopStopped, { age: formatAge(loop.last_pass_at, now, t) })} />
{/if}

{#if failure}
    <State kind="error" inline role="status" data-ledger="unavailable"
        title={t(LEDGER_KEYS.unavailable, { reason: failure })} />
{/if}

{#if loading}
    <State kind="loading" inline title={t(LEDGER_KEYS.loading)} />
{/if}

{#if isEmpty}
    <State data-ledger="empty" title={t(LEDGER_KEYS.emptyTitle)} hint={t(LEDGER_KEYS.emptyBody)} />
{/if}

<style>
    .ledger-keepalive {
        display: flex;
        flex-wrap: wrap;
        align-items: baseline;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .ledger-keepalive__label {
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-hint);
        letter-spacing: 0.04em;
    }
</style>
