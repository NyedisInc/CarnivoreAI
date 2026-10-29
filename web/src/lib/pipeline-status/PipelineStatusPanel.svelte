
<script lang="ts">
    import { onDestroy, untrack } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { Button } from '../base';
    import type { Translate } from '../sessions/types';
    import { relative } from '../../opscenter/lib/format';
    import '../settings-page/panel-kit/panel-kit.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { rebuildPlugin, type Fetcher } from './api';
    import { pluginNameKey, statusWords, type Words } from './model';
    import { acquireStatus } from './store.svelte';
    import PipelineSquares from './PipelineSquares.svelte';
    import './pipeline-status.css';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
        compact?: boolean;
        selected?: string | undefined;
    }
    let { t = reactiveT, fetcher, compact = false, selected = $bindable(undefined) }: Props = $props();

    const { status, release } = untrack(() => acquireStatus(fetcher));
    onDestroy(release);

    let asking = $state('');
    let busy = $state(false);
    let note = $state('');
    let problem = $state('');

    const nameOf = (id: string): string => t(pluginNameKey(id));
    const words = $derived(status.data ? statusWords(status.data, nameOf) : null);
    const lastDelivery = $derived(status.data?.last_delivery_at
        ? relative(Math.max(0, (Date.now() / 1000 - status.data.last_delivery_at) / 60)) : '');
    const plugins = $derived(status.data ? Object.entries(status.data.plugins) : []);

    function ask(id: string): void {
        problem = '';
        note = '';
        asking = asking === id ? '' : id;
    }

    async function confirm(id: string): Promise<void> {
        busy = true;
        problem = '';
        note = '';
        try {
            await rebuildPlugin(id, fetcher);
            note = t('pipeline.rebuild.started');
            asking = '';
        } catch (error) {
            problem = errorText(error);
        } finally {
            busy = false;
            void status.refresh(true);
        }
    }
</script>

{#snippet line(state: string, said: Words)}
    <p class="ps-line" data-ps="line" data-ps-state={state}>
        <span class="ps-state ps-state--{said.tone}" data-ps="state">{t(said.key, said.params)}</span>
        {#if lastDelivery}<span data-ps="last">{t('pipeline.status.last', { when: lastDelivery })}</span>{/if}
    </p>
{/snippet}

{#snippet confirmBox(id: string)}
    <div class="tm__warn" role="alert" data-ps="rebuild-panel" data-ps-for={id}>
        <p>{t('pipeline.rebuild.warning')}</p>
        <div class="tm__actions">
            <Button data-ps="cancel" onclick={() => ask(id)}>{t('pipeline.rebuild.cancel')}</Button>
            <Button variant="danger" data-ps="confirm" disabled={busy} onclick={() => void confirm(id)}>{t('pipeline.rebuild.confirm')}</Button>
        </div>
    </div>
{/snippet}

<div class="tm" class:ps--compact={compact} data-ps="screen">
    {#if status.data && words}
        {#if compact}
            <div class="ps-top" data-ps="top">
                {#if selected === undefined}
                    <PipelineSquares status={status.data} {nameOf} {t} />
                {:else}
                    <PipelineSquares status={status.data} {nameOf} {t} filterable bind:selected />
                {/if}
                {@render line(status.data.state, words)}
            </div>
        {:else}
            {@render line(status.data.state, words)}
            <div class="ps-rows" data-ps="rows">
                {#each plugins as [id, plugin] (id)}
                    <div class="ps-row" data-ps-plugin={id}>
                        <div class="ps-row__head">
                            <span class="ps-row__name">{nameOf(id)}</span>
                            <Button data-ps="rebuild" disabled={busy || plugin.rebuilding}
                                aria-expanded={asking === id} onclick={() => ask(id)}>{t('pipeline.rebuild')}</Button>
                        </div>
                        <div class="ps-row__facts">
                            <span data-ps="lag">{plugin.rebuilding ? t('pipeline.plugin.rebuilding') : plugin.lag.files > 0 ? t('pipeline.plugin.waiting', { files: plugin.lag.files }) : t('pipeline.plugin.caught_up')}</span>
                        </div>
                        {#if plugin.failures > 0 && plugin.last_error}
                            <p class="tm__problem" data-ps="failing">{t('pipeline.plugin.failing', { reason: plugin.last_error })}</p>
                        {/if}
                        {#if asking === id}{@render confirmBox(id)}{/if}
                    </div>
                {/each}
            </div>
        {/if}
        {#if note}<p class="tm__note" role="status" data-ps="note">{note}</p>{/if}
        {#if problem}<p class="tm__problem" role="alert" data-ps="problem">{problem}</p>{/if}
    {:else if status.status === 'error' || status.status === 'unavailable'}
        <p class="tm__problem" role="alert" data-ps="problem">{status.error ?? t('pipeline.status.unavailable')}</p>
    {:else}
        <p class="tm__sub">{t('pipeline.status.loading')}</p>
    {/if}
</div>
