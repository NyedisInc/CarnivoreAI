
<script lang="ts">
    import { onDestroy } from 'svelte';
    import { t as reactiveT, authFetch, resourcePush, failureReason, type Translate } from '../sdk';
    import { Button, Checkbox, IconButton, List, ListRow, ModalShell, State } from '../sdk/ui';
    import { canRestartNow, movable, showsProgress, sortedCounts, type RolloutPreview, type RolloutView } from './rollout-model';

    interface Props {
        close: (value: boolean | null) => void;
        t?: Translate;
        fetcher?: typeof authFetch;
        pollMs?: number;
    }
    const { close, t = reactiveT, fetcher = authFetch, pollMs = 30000 }: Props = $props();

    const ROUTE = '/argent/rollout';
    let preview = $state<RolloutPreview | null>(null);
    let view = $state<RolloutView | null>(null);
    let armed = $state(false);
    let busy = $state(false);
    let problem = $state('');
    let started = $state(false);

    const progress = $derived(showsProgress(view));
    const off = $derived((view?.direction || preview?.direction) === 'off');
    const waiting = $derived(movable(preview));

    async function load(): Promise<void> {
        try {
            view = await fetcher<RolloutView>(ROUTE);
            if (!showsProgress(view)) preview = await fetcher<RolloutPreview>(`${ROUTE}/preview`);
            problem = '';
        } catch (error) {
            problem = failureReason(error);
        }
    }
    void load();
    const stop = resourcePush().pushOrPoll(() => void load(), pollMs, ['argent_rollout']);
    onDestroy(stop);

    async function send(path: string, body: Record<string, unknown>): Promise<boolean> {
        busy = true;
        problem = '';
        try {
            view = await fetcher<RolloutView>(`${ROUTE}${path}`, { method: 'POST', body: JSON.stringify(body) });
            return true;
        } catch (error) {
            problem = failureReason(error);
            return false;
        } finally {
            busy = false;
        }
    }
    const start = async () => { if (await send('', { action: 'start' })) started = true; };
</script>

<ModalShell look="titlerow" title={t('argent.rollout.title')} dismissable={!busy} onCancel={() => close(started || null)}>
    <div data-argent="rollout">
        {#if progress && view}
            <p class="tm__sub" role="status" data-argent="run">{t(`argent.rollout.run.${view.state}`)}{view.reason ? `: ${view.reason}` : ''}</p>
            <p class="tm__sub" data-argent="counts">
                {sortedCounts(view.counts).map(([state, n]) => t('argent.rollout.count', { n, state: t(`argent.rollout.state.${state}`) })).join(', ')}
            </p>
            <List density="dense" label={t('argent.rollout.rows')}>
                {#each view.rows as row (row.tmux_name)}
                    <ListRow primary={row.tmux_name} secondary={row.reason} meta={t(`argent.rollout.state.${row.state}`)} data-argent-row={row.tmux_name}>
                        {#snippet actions()}
                            {#if canRestartNow(row)}
                                <Button size="sm" variant="danger" disabled={busy || !armed} data-argent="restart-now"
                                    onclick={() => void send('/restart-now', { tmux_name: row.tmux_name })}>{t('argent.rollout.restart_now')}</Button>
                            {/if}
                        {/snippet}
                    </ListRow>
                {/each}
            </List>
            <Checkbox tone="danger" label={t('argent.rollout.arm_row')} bind:checked={armed} disabled={busy} data-argent="arm" />
        {:else if preview}
            <p class="modal-description" data-argent="summary">
                {waiting === 0 ? t('argent.rollout.nothing') : t(off ? 'argent.rollout.will_off' : 'argent.rollout.will_on', { n: waiting })}
            </p>
            {#if preview.adopted > 0}<p class="tm__sub" data-argent="adopted">{t('argent.rollout.adopted', { n: preview.adopted })}</p>{/if}
            {#if preview.subagents + preview.background > 0}
                <State kind="warn" inline data-argent="dies"
                    title={t('argent.rollout.dies', { subagents: preview.subagents, background: preview.background })} />
            {/if}
            {#if sortedCounts(preview.excluded).length}
                <p class="tm__sub" data-argent="excluded-head">{t('argent.rollout.excluded')}</p>
                <List density="dense" label={t('argent.rollout.excluded')}>
                    {#each sortedCounts(preview.excluded) as [reason, n] (reason)}
                        <ListRow primary={reason} meta={String(n)} data-argent-excluded={reason} />
                    {/each}
                </List>
            {/if}
            {#if waiting > 0}
                <Checkbox tone="danger" label={t('argent.rollout.arm')} hint={t('argent.rollout.arm_hint')} bind:checked={armed} disabled={busy} data-argent="arm" />
            {/if}
        {:else if !problem}
            <p class="tm__sub">{t('argent.rollout.loading')}</p>
        {/if}
        {#if problem}<State kind="error" inline title={problem} data-argent="problem" />{/if}
    </div>
    {#snippet footer()}
        {#if progress && view}
            {#if view.state === 'paused'}
                <Button variant="confirm" disabled={busy} data-argent="resume" onclick={() => void send('', { action: 'resume' })}>{t('argent.rollout.resume')}</Button>
            {/if}
            <Button variant="secondary" disabled={busy} data-argent="cancel-run" onclick={() => void send('', { action: 'cancel' })}>{t('argent.rollout.cancel_run')}</Button>
            <Button variant="secondary" disabled={busy} onclick={() => close(started || null)}>{t('argent.rollout.done')}</Button>
        {:else}
            <Button variant="secondary" disabled={busy} data-argent="not-now" onclick={() => close(started || null)}>{t('argent.rollout.not_now')}</Button>
            <Button variant="confirm" disabled={busy || !armed || waiting === 0} data-argent="start" onclick={() => void start()}>{t('argent.rollout.start')}</Button>
        {/if}
    {/snippet}
</ModalShell>
