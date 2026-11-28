
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Tag from '../base/Tag.svelte';
    import { errorMessageOf, type PluginInspectorSnapshot } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from './cplugs-adapter';
    import {
        cpuLabel,
        healthPillStatusKey,
        healthPillTone,
        isPillPaused,
        lastCallSummary,
        restartCountOf,
        rssLabel,
    } from './plugin-health-pill';

    interface Props {
        plugin: CplugItem;
        snapshot?: PluginInspectorSnapshot | null;
        busy?: boolean;
        onLogs?: (cplugId: string) => void;
        onRestart: (cplugId: string) => Promise<unknown>;
        onPauseToggle: (cplugId: string, paused: boolean) => Promise<unknown>;
        t: Translate;
    }

    const { plugin, snapshot = null, busy = false, onLogs, onRestart, onPauseToggle, t }: Props = $props();

    let acting = $state(false);
    let actionError = $state<string | null>(null);

    const watchdog = $derived(snapshot?.watchdog ?? plugin.watchdog ?? null);
    const pillTone = $derived(healthPillTone(plugin, snapshot));
    const statusKey = $derived(healthPillStatusKey(plugin, snapshot));
    const paused = $derived(isPillPaused(plugin, snapshot));
    const restarts = $derived(restartCountOf(plugin, snapshot));
    const rss = $derived(rssLabel(watchdog, t));
    const cpu = $derived(cpuLabel(watchdog, t));
    const lastCall = $derived(lastCallSummary(snapshot, watchdog, plugin.watchdog));
    const isBusy = $derived(busy || acting);

    async function handleRestart(): Promise<void> {
        if (isBusy) return;
        acting = true;
        actionError = null;
        try {
            await onRestart(plugin.cplugId);
        } catch (err) {
            actionError = errorMessageOf(err);
        } finally {
            acting = false;
        }
    }

    async function handlePauseToggle(): Promise<void> {
        if (isBusy) return;
        acting = true;
        actionError = null;
        try {
            await onPauseToggle(plugin.cplugId, !paused);
        } catch (err) {
            actionError = errorMessageOf(err);
        } finally {
            acting = false;
        }
    }
</script>

<div class="pl-health-pill" data-health-pill={plugin.cplugId}>
    <div class="pl-health-pill__metrics">
        <Tag tone={pillTone} data-pill-status>{t(statusKey)}</Tag>
        <span class="pl-health-pill__stat" data-pill-rss data-tone={rss?.tone ?? 'neutral'}>
            {rss ? rss.text : t('plugins.page.health_pill.rss_none')}
        </span>
        {#if cpu}
            <span class="pl-health-pill__stat" data-pill-cpu data-tone={cpu.tone}>
                {cpu.text}
            </span>
        {/if}
        <span class="pl-health-pill__stat" data-pill-restarts>
            {t('plugins.page.health_pill.restarts', { count: restarts })}
        </span>
    </div>

    {#if lastCall}
        <p class="pl-health-pill__call" data-pill-last-call>
            {t('plugins.page.health_pill.last_call', { summary: lastCall })}
        </p>
    {/if}

    <div class="pl-health-pill__actions">
        <Button
            size="sm"
            variant="quiet"
            data-pill-logs
            disabled={isBusy || !onLogs}
            onclick={() => onLogs?.(plugin.cplugId)}
        >
            {t('plugins.page.health_pill.logs')}
        </Button>
        <Button
            size="sm"
            variant="secondary"
            data-pill-restart
            disabled={isBusy}
            onclick={() => void handleRestart()}
        >
            {t('plugins.page.health_pill.restart')}
        </Button>
        <Button
            size="sm"
            variant="secondary"
            data-pill-pause
            disabled={isBusy}
            onclick={() => void handlePauseToggle()}
        >
            {t(paused ? 'plugins.page.health_pill.resume' : 'plugins.page.health_pill.pause')}
        </Button>
    </div>

    {#if actionError}
        <p class="pl-health-pill__error" role="alert" data-pill-error>{actionError}</p>
    {/if}
</div>

<style>
    @layer components {
        .pl-health-pill {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
            padding: var(--oc-space-2);
            border: var(--oc-border) solid var(--oc-line-surface);
            border-radius: var(--oc-radius-panel);
            background: var(--oc-surface-raised);
            font-variant-numeric: tabular-nums;
        }

        .pl-health-pill__metrics {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-2);
        }

        .pl-health-pill__stat {
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
        }

        .pl-health-pill__stat[data-tone='warn'] {
            color: var(--oc-yellow);
        }

        .pl-health-pill__stat[data-tone='danger'] {
            color: var(--oc-coral);
        }

        .pl-health-pill__call {
            margin: 0;
            color: var(--oc-text-dim);
            font-size: var(--oc-fs-micro);
            overflow-wrap: anywhere;
        }

        .pl-health-pill__actions {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: var(--oc-space-1-5);
        }

        .pl-health-pill__error {
            margin: 0;
            color: var(--oc-coral);
            font-size: var(--oc-fs-label);
            overflow-wrap: anywhere;
        }
    }
</style>
