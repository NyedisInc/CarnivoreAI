
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT, authFetch, resourcePush, failureReason, type Translate } from '../sdk';
    import { Button, State } from '../sdk/ui';

    interface Outage { enabled: boolean; active: boolean; reason: string; tethered: number; key_expiring: number; rollout_paused: boolean }
    interface Restarted { restarted: number; waiting: Record<string, number> }

    interface Props { t?: Translate; fetcher?: typeof authFetch; pollMs?: number }
    const { t = reactiveT, fetcher = authFetch, pollMs = 30000 }: Props = $props();

    const reasonKey = (reason: string): string => (reason.split(' ')[1] === 'errors' ? 'errors' : 'down');

    let outage = $state<Outage | null>(null);
    let busy = $state(false);
    let problem = $state('');
    let result = $state<Restarted | null>(null);

    async function load(): Promise<void> {
        try {
            outage = await fetcher<Outage>('/argent/outage');
            if (!outage.active) result = null;
        } catch {
            outage = null;
        }
    }
    const refresh = () => void load();
    refresh();
    const stop = resourcePush().pushOrPoll(refresh, pollMs, ['argent_status', 'argent_rollout']);
    onDestroy(stop);

    async function restart(): Promise<void> {
        busy = true;
        problem = '';
        try {
            result = await fetcher<Restarted>('/argent/outage/restart-direct', { method: 'POST' });
            await load();
        } catch (error) {
            problem = failureReason(error);
        } finally {
            busy = false;
        }
    }
    const waiting = $derived(result ? Object.values(result.waiting).reduce((a, b) => a + b, 0) : 0);
</script>

{#if outage?.enabled && (outage.active || outage.rollout_paused || outage.key_expiring > 0)}
    <div data-argent="outage">
        {#if outage.active}
            <State kind="error" inline title={t('argent.outage.title')} data-argent="outage-title" />
            <p class="tm__sub" role="status" data-argent="outage-reason">{t(`argent.outage.reason.${reasonKey(outage.reason)}`)}</p>
            <p class="tm__sub" data-argent="outage-detail">{t('argent.outage.detail', { n: outage.tethered })}</p>
            <div class="tm__actions">
                <Button size="sm" variant="confirm" disabled={busy || outage.tethered === 0} data-argent="restart-direct" onclick={() => void restart()}>
                    {t('argent.outage.restart')}
                </Button>
            </div>
            {#if result}<p class="tm__sub" data-argent="outage-result">{t('argent.outage.restarted', { n: result.restarted, w: waiting })}</p>{/if}
        {/if}
        {#if outage.rollout_paused}<p class="tm__sub" data-argent="outage-paused">{t('argent.outage.paused')}</p>{/if}
        {#if outage.key_expiring > 0}<p class="tm__sub" data-argent="outage-keys">{t('argent.outage.keys', { n: outage.key_expiring })}</p>{/if}
        {#if problem}<State kind="error" inline title={problem} data-argent="outage-problem" />{/if}
    </div>
{/if}
