
<script lang="ts">
    import Button from '../base/Button.svelte';
    import State from '../base/State.svelte';
    import Switch from '../base/Switch.svelte';
    import { onDestroy, untrack } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import './panel-kit/panel-kit.css';
    import { statsSync } from './stats-collection/sync.svelte';
    import { errorText } from './panel-kit/error-text';
    import {
        fetchMaintenance, setStatsEnabled, sizeText, startBackfill, startClear,
        type Fetcher, type Maintenance,
    } from './stats-collection/api';

    const POLL_MS = 1500;

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        pollMs?: number;
        part?: 'all' | 'main' | 'lifecycle';
    }
    const { t = reactiveT, fetcher, pollMs = POLL_MS, part = 'all' }: Props = $props();

    let view = $state<Maintenance | null>(null);
    let busy = $state(false);
    let confirming = $state(false);
    let note = $state('');
    let problem = $state('');
    let timer: ReturnType<typeof setTimeout> | null = null;

    const working = $derived(view !== null && (view.clear.state === 'running' || view.backfill.state !== 'idle'));

    async function load(): Promise<void> {
        try {
            view = await fetchMaintenance(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
        if (timer !== null) clearTimeout(timer);
        timer = working && pollMs > 0 ? setTimeout(() => void load(), pollMs) : null;
    }
    $effect(() => {
        void statsSync.epoch;
        untrack(() => void load());
    });
    onDestroy(() => { if (timer !== null) clearTimeout(timer); });

    async function act(run: () => Promise<unknown>, done: string): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await run();
            note = done;
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
            confirming = false;
            statsSync.epoch += 1;
        }
    }

    const toggle = (next: boolean): Promise<void> => act(() => setStatsEnabled(next, view!.revision, fetcher),
        next ? t('settings.stats.on_note') : t('settings.stats.off_note'));
    const clearNow = (): Promise<void> => act(() => startClear(fetcher), '');
    const catchUp = (): Promise<void> => act(() => startBackfill(fetcher), t('settings.stats.backfill_started'));
</script>

<div class="tm" data-stats="panel" data-stats-part={part}>
    {#if view}
        {#if part !== 'lifecycle'}
            <Switch label={t('settings.stats.label')} bind:checked={() => view?.enabled ?? false, (next) => void toggle(next)} disabled={busy || view.clear.state === 'running'}
                data-stats="switch" />
            <p class="tm__sub">{t('settings.stats.size', { size: sizeText(view.db_bytes) })}</p>
        {/if}

        {#if view.enabled}
            {#if part !== 'lifecycle'}
                <p class="tm__sub">{t('settings.stats.backfill_hint')}</p>
                <div class="tm__actions">
                    <Button variant="confirm" data-stats="backfill"
                        disabled={busy || view.backfill.state !== 'idle'} onclick={() => void catchUp()}>
                        {t('settings.stats.backfill')}
                    </Button>
                </div>
                {#if view.backfill.state !== 'idle'}
                    <State inline role="status" data-stats="backfill-progress"
                        title={t('settings.stats.backfill_progress', { left: view.backfill.pending_sources, total: view.backfill.known_sources })} />
                {/if}
            {:else}
                <div class="tm__actions">
                    <Button variant="danger" data-stats="clear" disabled>{t('settings.stats.clear')}</Button>
                </div>
                <p class="tm__sub" data-stats="clear-needs-off">{t('settings.stats.clear_needs_off')}</p>
            {/if}
        {:else}
            {#if part !== 'lifecycle'}<p class="tm__sub">{t('settings.stats.off_hint')}</p>{/if}
            {#if part !== 'main'}
                {#if confirming}
                    <State kind="warn" title={t('settings.stats.clear_warning', { size: sizeText(view.db_bytes) })} data-stats="warn">
                        {#snippet actions()}
                            <Button data-stats="cancel" disabled={busy} onclick={() => (confirming = false)}>{t('settings.stats.cancel')}</Button>
                            <Button variant="danger" data-stats="confirm" disabled={busy} onclick={() => void clearNow()}>{t('settings.stats.confirm')}</Button>
                        {/snippet}
                    </State>
                {:else}
                    <div class="tm__actions">
                        <Button variant="danger" data-stats="clear"
                            disabled={busy || view.clear.state === 'running'} onclick={() => (confirming = true)}>
                            {t('settings.stats.clear')}
                        </Button>
                    </div>
                {/if}
            {/if}
        {/if}

        {#if part !== 'main'}
            {#if view.clear.state === 'running'}
                <State inline role="status" data-stats="clear-progress" title={t('settings.stats.clearing', { phase: view.clear.phase })} />
            {:else if view.clear.state === 'done' && view.clear.reclaimed_bytes !== null}
                <State inline role="status" data-stats="clear-done"
                    title={t('settings.stats.cleared', {
                        freed: sizeText(view.clear.reclaimed_bytes),
                        before: sizeText(view.clear.bytes_before ?? 0),
                        after: sizeText(view.clear.bytes_after ?? 0),
                    })} />
            {:else if view.clear.state === 'failed'}
                <State kind="error" inline data-stats="clear-failed" title={t('settings.stats.clear_failed', { reason: view.clear.error })} />
            {/if}
        {/if}
    {:else if !problem}
        <p class="tm__sub">{t('settings.stats.loading')}</p>
    {/if}
    {#if note && part !== 'lifecycle'}<State inline role="status" data-stats="note" title={note} />{/if}
    {#if problem}<State kind="error" inline data-stats="problem" title={problem} />{/if}
</div>
