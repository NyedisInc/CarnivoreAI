
<script lang="ts">
    import { Button, Fold, State, Tag } from '../base';
    import { panels } from '../cplug-ui/panel-views.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import { errorMessageOf, pluginsStore, type PluginInspectorSnapshot } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';
    import Tabs, { panelAttrs } from '../../opscenter/ui/Tabs.svelte';
    import type { CplugItem } from './cplugs-adapter';
    import {
        capabilityCheckKey,
        categorizeLogs,
        deriveDevLeaseSummary,
        formatCpuUsage,
        formatDiskUsage,
        formatDuration,
        formatLatency,
        formatRssUsage,
        formatStrikes,
        formatTimestamp,
        inspectorStatusInfo,
        inspectorTabs,
        isSidecarSubject,
        mergeSurfaces,
        rpcTraceKey,
        secretsSummary,
        type InspectorTabId,
    } from './dev-inspector';
    import './dev-inspector.css';

    interface Props {
        subjectId: string;
        plugin?: CplugItem | null;
        snapshot: PluginInspectorSnapshot | null;
        loading?: boolean;
        initialTab?: InspectorTabId;
        busy?: boolean;
        showControls?: boolean;
        onRestart?: (cplugId: string) => Promise<unknown>;
        onPauseToggle?: (cplugId: string, paused: boolean) => Promise<unknown>;
        t?: Translate;
    }

    const {
        subjectId,
        plugin = null,
        snapshot,
        loading = false,
        initialTab = 'trace',
        busy = false,
        showControls,
        onRestart = (id) => pluginsStore.restartPlugin(id),
        onPauseToggle = (id, paused) => (paused ? pluginsStore.pausePlugin(id) : pluginsStore.resumePlugin(id)),
        t = appT,
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    let activeTab = $state<InspectorTabId>(initialTab);
    let acting = $state(false);
    let actionError = $state<string | null>(null);
    let lastSubjectId = '';

    $effect(() => {
        if (subjectId !== lastSubjectId) {
            lastSubjectId = subjectId;
            actionError = null;
            activeTab = initialTab;
        }
    });

    const isSidecar = $derived(showControls ?? isSidecarSubject(plugin, snapshot));
    const statusInfo = $derived(inspectorStatusInfo(plugin, snapshot));
    const watchdog = $derived(snapshot?.watchdog ?? plugin?.watchdog ?? null);
    const rss = $derived(formatRssUsage(watchdog, t));
    const cpu = $derived(formatCpuUsage(watchdog, t));
    const disk = $derived(formatDiskUsage(watchdog, t));
    const strikes = $derived(formatStrikes(watchdog, snapshot?.state ?? plugin?.state, t));
    const uptimeLabel = $derived(formatDuration(watchdog?.uptime_seconds, t));
    const leaseSummary = $derived(deriveDevLeaseSummary(snapshot, plugin, t));
    const formattedLogs = $derived(categorizeLogs(snapshot?.logs_tail, t));
    const surfacesSummary = $derived(mergeSurfaces(subjectId, snapshot?.surfaces ?? null, panels.list));
    const secrets = $derived(secretsSummary(snapshot?.secrets_status ?? plugin?.secretsStatus));
    const rpcTrace = $derived(snapshot?.rpc_trace ?? []);
    const capabilityChecks = $derived(snapshot?.capability_checks ?? []);
    const isBusy = $derived(busy || acting);

    const tabs = $derived(
        inspectorTabs(t, {
            trace: rpcTrace.length,
            capabilities: capabilityChecks.length,
            surfaces: surfacesSummary.totalActiveCount,
            logs: formattedLogs.length,
            hasReloadAlert:
                leaseSummary.needsReconsent ||
                leaseSummary.reloadErrors.length > 0 ||
                leaseSummary.uiErrors.length > 0,
            hasCrashLoop: statusInfo.crashLoop || strikes.crashLoop,
        }),
    );

    const idBase = $derived(`pl-inspector-${subjectId || 'none'}`);

    async function handleRestart(): Promise<void> {
        if (!subjectId || isBusy) return;
        acting = true;
        actionError = null;
        try {
            await onRestart(subjectId);
        } catch (err) {
            actionError = errorMessageOf(err);
        } finally {
            acting = false;
        }
    }

    async function handlePauseToggle(): Promise<void> {
        if (!subjectId || isBusy) return;
        acting = true;
        actionError = null;
        try {
            await onPauseToggle(subjectId, !statusInfo.paused);
        } catch (err) {
            actionError = errorMessageOf(err);
        } finally {
            acting = false;
        }
    }
</script>

{#if isSidecar}
    <div class="pl-inspector__controls" data-inspector-controls>
        <span class="pl-inspector__label">{t('plugins.page.inspector.watchdog.controls')}</span>
        <div class="pl-inspector__actions">
            <Button
                size="sm"
                variant="secondary"
                data-inspector-restart
                disabled={isBusy}
                onclick={() => void handleRestart()}
            >
                {t('plugins.page.inspector.watchdog.restart')}
            </Button>
            <Button
                size="sm"
                variant="secondary"
                data-inspector-pause
                disabled={isBusy}
                onclick={() => void handlePauseToggle()}
            >
                {t(
                    statusInfo.paused
                        ? 'plugins.page.inspector.watchdog.resume'
                        : 'plugins.page.inspector.watchdog.pause',
                )}
            </Button>
        </div>
    </div>
{/if}

{#if actionError}
    <p class="pl-inspector__error" role="alert" data-inspector-action-error>{actionError}</p>
{/if}

{#if leaseSummary.needsReconsent}
    <div class="pl-inspector__banner" data-tone="warn" role="status" data-inspector-widening-banner>
        <p class="pl-inspector__banner-text">
            {leaseSummary.widening?.reason ?? t('plugins.page.inspector.dev_lease.widened')}
        </p>
        {#if leaseSummary.widening && leaseSummary.widening.widened.length > 0}
            <p class="pl-inspector__banner-detail">
                {t('plugins.page.inspector.dev_lease.widened_list', {
                    names: leaseSummary.widening.widened.join(', '),
                })}
            </p>
        {/if}
    </div>
{/if}

{#if statusInfo.crashLoop || strikes.crashLoop}
    <div class="pl-inspector__banner" data-tone="danger" role="alert" data-inspector-crash-loop-banner>
        <p class="pl-inspector__banner-text">{t('plugins.page.inspector.watchdog.crash_loop')}</p>
        <p class="pl-inspector__banner-detail">{t('plugins.page.inspector.watchdog.crash_loop_note')}</p>
    </div>
{/if}

<Tabs
    {tabs}
    active={activeTab}
    onSelect={(id) => (activeTab = id as InspectorTabId)}
    label={t('plugins.page.inspector.tabs')}
    {idBase}
    compact
/>

<div class="pl-inspector__panel" {...panelAttrs(idBase, activeTab)} data-inspector-panel={activeTab}>
    {#if snapshot === null && loading}
        <State kind="loading" title={t('plugins.page.inspector.loading')} />
    {:else if activeTab === 'trace'}
        <section class="pl-inspector__section" data-inspector-section="trace">
            <div class="pl-inspector__section-head">
                <h3 class="pl-inspector__label">{t('plugins.page.inspector.trace.heading')}</h3>
                <Tag tone="neutral">{rpcTrace.length}</Tag>
            </div>
            {#if rpcTrace.length === 0}
                <State kind="empty" title={t('plugins.page.inspector.trace.empty')} />
            {:else}
                <ul class="pl-inspector__list" data-inspector-trace-list>
                    {#each rpcTrace as entry, i (rpcTraceKey(entry, i))}
                        <li
                            class="pl-inspector__row"
                            data-inspector-trace-row
                            data-trace-ok={entry.ok ? 'true' : 'false'}
                        >
                            <div class="pl-inspector__row-top">
                                <Tag tone={entry.source === 'cli_sock' ? 'info' : 'neutral'} data-trace-source>
                                    {t(
                                        entry.source === 'cli_sock'
                                            ? 'plugins.page.inspector.trace.source_cli'
                                            : 'plugins.page.inspector.trace.source_rpc',
                                    )}
                                </Tag>
                                <span class="pl-inspector__row-main" data-trace-method>{entry.method}</span>
                                <Tag tone={entry.ok ? 'ok' : 'danger'} data-trace-status>
                                    {t(
                                        entry.ok
                                            ? 'plugins.page.inspector.trace.ok'
                                            : 'plugins.page.inspector.trace.err',
                                    )}
                                </Tag>
                                <span class="pl-inspector__row-meta" data-trace-latency>
                                    {formatLatency(entry.latency_ms)}
                                </span>
                                <span class="pl-inspector__row-ts">{formatTimestamp(entry.ts)}</span>
                            </div>
                            {#if entry.target}
                                <p class="pl-inspector__row-detail" data-trace-target>{entry.target}</p>
                            {/if}
                            {#if !entry.ok && (entry.error_code || entry.error_message)}
                                <p class="pl-inspector__row-error" data-trace-error>
                                    {[entry.error_code, entry.error_message].filter(Boolean).join(': ')}
                                </p>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>
    {:else if activeTab === 'capabilities'}
        <section class="pl-inspector__section" data-inspector-section="capabilities">
            <div class="pl-inspector__section-head">
                <h3 class="pl-inspector__label">{t('plugins.page.inspector.capabilities.heading')}</h3>
                <Tag tone="neutral">{capabilityChecks.length}</Tag>
            </div>
            {#if capabilityChecks.length === 0}
                <State kind="empty" title={t('plugins.page.inspector.capabilities.empty')} />
            {:else}
                <ul class="pl-inspector__list" data-inspector-capabilities-list>
                    {#each capabilityChecks as entry, i (capabilityCheckKey(entry, i))}
                        <li
                            class="pl-inspector__row"
                            data-inspector-capability-row
                            data-cap-allowed={entry.allowed ? 'true' : 'false'}
                        >
                            <div class="pl-inspector__row-top">
                                <Tag tone={entry.allowed ? 'ok' : 'danger'} data-cap-verdict>
                                    {t(
                                        entry.allowed
                                            ? 'plugins.page.inspector.capabilities.allowed'
                                            : 'plugins.page.inspector.capabilities.denied',
                                    )}
                                </Tag>
                                <span class="pl-inspector__row-main" data-cap-permission>{entry.permission}</span>
                                <span class="pl-inspector__row-ts">{formatTimestamp(entry.ts)}</span>
                            </div>
                            {#if entry.caller || entry.reason}
                                <p class="pl-inspector__row-detail" data-cap-detail>
                                    {[
                                        entry.caller
                                            ? t('plugins.page.inspector.capabilities.caller', { caller: entry.caller })
                                            : null,
                                        entry.reason ?? null,
                                    ]
                                        .filter(Boolean)
                                        .join(' | ')}
                                </p>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>
    {:else if activeTab === 'watchdog'}
        <section class="pl-inspector__section" data-inspector-section="watchdog">
            <div class="pl-inspector__section-head">
                <h3 class="pl-inspector__label">{t('plugins.page.inspector.watchdog.heading')}</h3>
                <Tag tone={strikes.tone} data-inspector-strikes-badge>{strikes.text}</Tag>
            </div>
            <dl class="pl-inspector__facts" data-inspector-watchdog-facts>
                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.rss')}</dt>
                <dd class="pl-inspector__fact-val" data-tone={rss.tone} data-inspector-rss>{rss.text}</dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.cpu')}</dt>
                <dd class="pl-inspector__fact-val" data-tone={cpu.tone} data-inspector-cpu>{cpu.text}</dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.disk_bytes')}</dt>
                <dd class="pl-inspector__fact-val" data-tone={disk.tone} data-inspector-disk-bytes>
                    {disk.bytesText}
                </dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.disk_files')}</dt>
                <dd class="pl-inspector__fact-val" data-tone={disk.tone} data-inspector-disk-files>
                    {disk.filesText}
                </dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.uptime')}</dt>
                <dd class="pl-inspector__fact-val" data-inspector-uptime>{uptimeLabel}</dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.pid')}</dt>
                <dd class="pl-inspector__fact-val" data-inspector-pid>
                    {typeof watchdog?.pid === 'number' ? watchdog.pid : t('plugins.page.inspector.not_measured')}
                </dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.restarts')}</dt>
                <dd class="pl-inspector__fact-val" data-inspector-restarts>{watchdog?.restart_count ?? 0}</dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.watchdog.strikes')}</dt>
                <dd class="pl-inspector__fact-val" data-tone={strikes.tone} data-inspector-strikes>
                    {strikes.text}
                </dd>
            </dl>
        </section>
    {:else if activeTab === 'surfaces'}
        <section class="pl-inspector__section" data-inspector-section="surfaces">
            <div class="pl-inspector__section-head">
                <h3 class="pl-inspector__label">{t('plugins.page.inspector.surfaces.heading')}</h3>
                <Tag tone="neutral">{surfacesSummary.totalActiveCount}</Tag>
            </div>

            <div class="pl-inspector__subsection">
                <h4 class="pl-inspector__sublabel">{t('plugins.page.inspector.surfaces.declared')}</h4>
                {#if surfacesSummary.activeFlags.length === 0}
                    <p class="pl-inspector__muted">{t('plugins.page.inspector.none')}</p>
                {:else}
                    <div class="pl-inspector__chips" data-inspector-surface-flags>
                        {#each surfacesSummary.activeFlags as flag (flag)}
                            <Tag tone="accent" data-surface-flag={flag}>
                                {t(`plugins.page.inspector.surfaces.flag.${flag}`)}
                            </Tag>
                        {/each}
                    </div>
                {/if}
            </div>

            <div class="pl-inspector__subsection">
                <h4 class="pl-inspector__sublabel">{t('plugins.page.inspector.surfaces.live_widgets')}</h4>
                {#if surfacesSummary.livePanels.length === 0}
                    <p class="pl-inspector__muted" data-inspector-live-empty>
                        {t('plugins.page.inspector.surfaces.live_empty')}
                    </p>
                {:else}
                    <ul class="pl-inspector__list" data-inspector-live-panels>
                        {#each surfacesSummary.livePanels as view (view.key)}
                            <li class="pl-inspector__row" data-live-panel={view.kind}>
                                <div class="pl-inspector__row-top">
                                    <Tag tone={view.declarative ? 'info' : 'ok'}>
                                        {t(
                                            view.declarative
                                                ? 'plugins.page.inspector.surfaces.declarative'
                                                : 'plugins.page.inspector.surfaces.iframe',
                                        )}
                                    </Tag>
                                    <span class="pl-inspector__row-main">{view.title}</span>
                                    <span class="pl-inspector__row-meta">{view.kind}</span>
                                </div>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>

            <dl class="pl-inspector__facts" data-inspector-surface-facts>
                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.surfaces.tools')}</dt>
                <dd class="pl-inspector__fact-val" data-inspector-tools>
                    {surfacesSummary.tools.length > 0
                        ? surfacesSummary.tools.join(', ')
                        : t('plugins.page.inspector.none')}
                </dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.surfaces.routes')}</dt>
                <dd class="pl-inspector__fact-val" data-inspector-routes>
                    {surfacesSummary.routes.length > 0
                        ? surfacesSummary.routes.join(', ')
                        : t('plugins.page.inspector.none')}
                </dd>

                <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.surfaces.timers')}</dt>
                <dd class="pl-inspector__fact-val" data-inspector-timers>
                    {surfacesSummary.timers.length > 0
                        ? surfacesSummary.timers.join(', ')
                        : t('plugins.page.inspector.none')}
                </dd>

                {#if surfacesSummary.absentSurfaces.length > 0}
                    <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.surfaces.absent')}</dt>
                    <dd class="pl-inspector__fact-val" data-inspector-absent-surfaces>
                        {surfacesSummary.absentSurfaces.join(', ')}
                    </dd>
                {/if}
            </dl>

            {#if secrets.length > 0}
                <Fold label={t('plugins.page.inspector.surfaces.secrets')} count={secrets.length} open>
                    <ul class="pl-inspector__list" data-inspector-secrets>
                        {#each secrets as secret (secret.name)}
                            <li class="pl-inspector__row" data-inspector-secret={secret.name}>
                                <div class="pl-inspector__row-top">
                                    <span class="pl-inspector__row-main">{secret.name}</span>
                                    <Tag tone={secret.needsReentry ? 'warn' : secret.present ? 'ok' : 'danger'}>
                                        {t(
                                            secret.needsReentry
                                                ? 'plugins.page.inspector.surfaces.secret_reentry'
                                                : secret.present
                                                  ? 'plugins.page.inspector.surfaces.secret_present'
                                                  : 'plugins.page.inspector.surfaces.secret_missing',
                                        )}
                                    </Tag>
                                </div>
                            </li>
                        {/each}
                    </ul>
                </Fold>
            {/if}
        </section>
    {:else}
        <section class="pl-inspector__section" data-inspector-section="dev-lease">
            <div class="pl-inspector__section-head">
                <h3 class="pl-inspector__label">{t('plugins.page.inspector.dev_lease.heading')}</h3>
                <Tag tone={leaseSummary.active ? 'info' : 'neutral'} data-inspector-lease-status>
                    {t(
                        leaseSummary.active
                            ? 'plugins.page.inspector.dev_lease.active'
                            : 'plugins.page.inspector.dev_lease.inactive',
                    )}
                </Tag>
            </div>
            <dl class="pl-inspector__facts" data-inspector-lease-facts>
                {#if leaseSummary.sourceRealpath}
                    <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.dev_lease.source')}</dt>
                    <dd class="pl-inspector__fact-val" data-inspector-lease-source>
                        {leaseSummary.sourceRealpath}
                    </dd>
                {/if}
                {#if leaseSummary.baselineSha}
                    <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.dev_lease.sha')}</dt>
                    <dd class="pl-inspector__fact-val" data-inspector-lease-sha>
                        {leaseSummary.baselineSha}
                    </dd>
                {/if}
                {#if leaseSummary.ttlLabel}
                    <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.dev_lease.ttl')}</dt>
                    <dd class="pl-inspector__fact-val" data-inspector-lease-ttl>
                        {leaseSummary.ttlLabel}
                    </dd>
                {/if}
                {#if leaseSummary.lastReload}
                    <dt class="pl-inspector__fact-term">{t('plugins.page.inspector.dev_lease.last_reload')}</dt>
                    <dd class="pl-inspector__fact-val" data-inspector-last-reload>
                        {#if leaseSummary.lastReload.totalMs !== null}
                            {#if leaseSummary.lastReload.stageMs !== null && leaseSummary.lastReload.stopMs !== null && leaseSummary.lastReload.startMs !== null}
                                {t('plugins.page.inspector.dev_lease.reload_ms', {
                                    total: Math.round(leaseSummary.lastReload.totalMs),
                                    stage: Math.round(leaseSummary.lastReload.stageMs),
                                    stop: Math.round(leaseSummary.lastReload.stopMs),
                                    start: Math.round(leaseSummary.lastReload.startMs),
                                })}
                            {:else}
                                {t('plugins.page.inspector.dev_lease.reload_total', {
                                    total: Math.round(leaseSummary.lastReload.totalMs),
                                })}
                            {/if}
                        {:else if leaseSummary.lastReload.unchanged}
                            {t('plugins.page.inspector.dev_lease.unchanged')}
                        {:else}
                            {t('plugins.page.inspector.logs.source.reloaded')}
                        {/if}
                    </dd>
                {/if}
            </dl>
        </section>

        <section class="pl-inspector__section" data-inspector-section="logs">
            <div class="pl-inspector__section-head">
                <h3 class="pl-inspector__label">{t('plugins.page.inspector.logs.heading')}</h3>
                <Tag tone="neutral">{formattedLogs.length}</Tag>
            </div>
            {#if formattedLogs.length === 0}
                <State kind="empty" title={t('plugins.page.inspector.logs.empty')} />
            {:else}
                <ul class="pl-inspector__list" data-inspector-logs-list>
                    {#each formattedLogs as entry (entry.key)}
                        <li class="pl-inspector__row" data-inspector-log-row data-log-source={entry.source}>
                            <div class="pl-inspector__row-top">
                                <Tag tone={entry.tone} data-log-badge>
                                    {entry.sourceLabel}
                                </Tag>
                                <span class="pl-inspector__row-main" data-log-title>{entry.title}</span>
                                <span class="pl-inspector__row-ts">{entry.tsLabel}</span>
                            </div>
                            {#if entry.detail}
                                <p class="pl-inspector__row-detail" data-log-detail>{entry.detail}</p>
                            {/if}
                        </li>
                    {/each}
                </ul>
            {/if}
        </section>
    {/if}
</div>
