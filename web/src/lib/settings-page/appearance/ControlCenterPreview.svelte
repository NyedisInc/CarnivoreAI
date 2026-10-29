
<script lang="ts">
    import Icon from '../../../opscenter/ui/Icon.svelte';
    import Tabs, { type TabDef } from '../../../opscenter/ui/Tabs.svelte';
    import LimitGauge from '../../../opscenter/ui/LimitGauge.svelte';
    import type { Translate } from '../../sessions/types';
    import {
        SAMPLE_AGENTS,
        SAMPLE_METERS,
        SAMPLE_SESSION,
        SAMPLE_SHELLS,
        SAMPLE_TIMERS,
        sampleScale,
        samplePaceState,
        type SampleAgent,
        type SampleShell,
        type SampleTimer,
    } from './samples';

    interface Props {
        layout: 'a' | 'b' | 'c';
        t: Translate;
        inert?: boolean;
    }

    const { layout, t, inert = false }: Props = $props();

    type Kind = 'timers' | 'agents' | 'shells';
    let tab = $state<Kind>('agents');
    let filter = $state<'all' | Kind>('all');

    const COUNT: Record<Kind, number> = { timers: SAMPLE_TIMERS.length, agents: SAMPLE_AGENTS.length, shells: SAMPLE_SHELLS.length };
    const TOTAL = COUNT.timers + COUNT.agents + COUNT.shells;
    const previewTabs: TabDef[] = (['timers', 'agents', 'shells'] as const).map((id) => ({ id, label: t(`settings.footbarlayout.open.${id}`), badge: COUNT[id] }));
    const c = SAMPLE_METERS.context;
    const h = SAMPLE_METERS.window_5h;
    const w = SAMPLE_METERS.window_7d;

    const word = (key: string): string => t(`settings.controlcenter.${key}`);
</script>

{#snippet bar(pct: number, tone: string)}
    <span class="ccp-bar"><i class="ccp-bg-{tone}" style:width="{pct}%"></i></span>
{/snippet}

{#snippet gauge(m: typeof h)}
    <span class="ccp-gauge"><LimitGauge variant="fill" pct={m.pct} scale={sampleScale(m.tone)} paceElapsedPct={m.elapsedPct ?? null} paceState={samplePaceState(m)} meterText={`${m.short} ${m.pct}%`} height={6} ariaHidden /></span>
{/snippet}

{#snippet act(label: string, danger: boolean)}
    <span class="oc-btn oc-btn--sm ccp-act" class:oc-btn--danger={danger}>{label}</span>
{/snippet}

{#snippet timerRow(tm: SampleTimer, kind: boolean)}
    <div class="ccp-row">
        <div class="ccp-r1">
            {#if kind}<span class="ccp-kind">{word('kind.timer')}</span>{/if}
            <span class="ccp-nm">{tm.rule}</span><span class="ccp-tm ccp-c-ok">{tm.due}</span>
            {@render act(word('cancel'), false)}
        </div>
        <div class="ccp-r2" class:ccp-indent={kind}>{tm.task}</div>
    </div>
{/snippet}

{#snippet agentRow(a: SampleAgent, kind: boolean)}
    <div class="ccp-row">
        <div class="ccp-r1">
            {#if kind}<span class="ccp-kind">{word('kind.agent')}</span>{/if}
            <span class="ccp-st ccp-st-{a.state}"></span><span class="ccp-nm">{a.name}</span>
            <span class="ccp-state">{a.stateName}</span><span class="ccp-tm">{a.elapsed}</span>
            {@render act(word('stop'), true)}
        </div>
        <div class="ccp-r2" class:ccp-indent={kind}>{a.task}</div>
    </div>
{/snippet}

{#snippet shellRow(s: SampleShell, kind: boolean, nest: boolean)}
    <div class="ccp-row" class:ccp-nest={nest}>
        <div class="ccp-r1">
            {#if kind}<span class="ccp-kind">{word('kind.shell')}</span>{/if}
            <span class="ccp-nm">{s.id}</span><span class="ccp-tm">{s.elapsed}</span>
            {@render act(word('stop'), true)}
        </div>
        <div class="ccp-r2" class:ccp-indent={kind}>{s.cmd}</div>
        <div class="ccp-r3" class:ccp-indent={kind}>{s.detail}</div>
    </div>
{/snippet}

{#snippet head(kind: Kind, action: string, danger: boolean)}
    <div class="ccp-h">
        <span class="ccp-ht">{t(`settings.footbarlayout.open.${kind}`)}<b>{COUNT[kind]}</b></span>
        {@render act(action, danger)}
    </div>
{/snippet}

{#snippet list(kind: Kind)}
    {#if kind === 'timers'}
        {#each SAMPLE_TIMERS as tm (tm.rule)}{@render timerRow(tm, false)}{/each}
        <div class="ccp-more">{word('history')}</div>
    {:else if kind === 'agents'}
        {#each SAMPLE_AGENTS as a (a.id)}{@render agentRow(a, false)}{/each}
    {:else}
        {#each SAMPLE_SHELLS as s (s.id)}{@render shellRow(s, false, false)}{/each}
    {/if}
{/snippet}

{#snippet chip(id: 'all' | Kind, n: number, active: boolean)}
    {#if inert}
        <span class="ccp-tab" data-active={active}>{t(`settings.footbarlayout.open.${id}`)}<b>{n}</b></span>
    {:else}
        <button type="button" class="ccp-tab" aria-pressed={active} data-active={active} onclick={() => (filter = id)}>
            {t(`settings.footbarlayout.open.${id}`)}<b>{n}</b>
        </button>
    {/if}
{/snippet}

<div class="ccp" data-layout={layout} aria-hidden={inert ? 'true' : undefined}>
    <div class="ccp-band">
        <div>
            <span class="ccp-k">{word('context')}</span>
            <span class="ccp-v">{@render bar(c.pct, c.tone)}<span class="ccp-c-info">{c.pct}%</span><span class="ccp-dim">{c.detail}</span></span>
            <span class="ccp-k">{word('model')}</span>
            <span class="ccp-v"><span class="ccp-model">{SAMPLE_SESSION.model}</span><span class="ccp-eff">{SAMPLE_SESSION.effort}</span></span>
            <span class="ccp-k">{word('tokens')}</span>
            <span class="ccp-v">{SAMPLE_SESSION.tokens}</span>
        </div>
        <div>
            <span class="ccp-k">{word('window_5h')}</span>
            <span class="ccp-v">{@render gauge(h)}<span class="ccp-c-warn">{h.pct}%</span><span class="ccp-dim"><Icon name="reset" size={11} /> {h.reset} {h.at}</span></span>
            <span class="ccp-k">{word('window_7d')}</span>
            <span class="ccp-v">{@render gauge(w)}<span class="ccp-c-ok">{w.pct}%</span><span class="ccp-dim"><Icon name="reset" size={11} /> {w.reset}</span></span>
        </div>
        <div>
            <span class="ccp-k">{word('cost')}</span><span class="ccp-v">{SAMPLE_SESSION.cost}</span>
            <span class="ccp-k">{word('account')}</span><span class="ccp-v">{SAMPLE_SESSION.account}</span>
        </div>
    </div>

    {#if layout === 'a'}
        <div class="ccp-cols">
            <div class="ccp-col">{@render head('timers', word('cancel_all'), false)}{@render list('timers')}</div>
            <div class="ccp-col">{@render head('agents', word('stop_all'), true)}{@render list('agents')}</div>
            <div class="ccp-col">{@render head('shells', word('stop_all'), true)}{@render list('shells')}</div>
        </div>
    {:else if layout === 'b'}
        <div class="ccp-tabs">
            {#if inert}
                
                {#each previewTabs as def (def.id)}{@render chip(def.id as Kind, COUNT[def.id as Kind], tab === def.id)}{/each}
            {:else}
                <Tabs tabs={previewTabs} active={tab} onSelect={(id) => (tab = id as Kind)} label={t('control_center.label')} idBase="ccp" />
            {/if}
            <span class="ccp-fill"></span>
            {@render act(t('settings.controlcenter.stop_all_kind', { kind: t(`settings.footbarlayout.open.${tab}`) }), true)}
        </div>
        {@render list(tab)}
    {:else}
        <div class="ccp-tabs">
            {@render chip('all', TOTAL, filter === 'all')}
            {@render chip('agents', COUNT.agents, filter === 'agents')}
            {@render chip('shells', COUNT.shells, filter === 'shells')}
            {@render chip('timers', COUNT.timers, filter === 'timers')}
            <span class="ccp-fill"></span>
            {@render act(word('interrupt'), false)}
            {@render act(word('stop_all'), true)}
        </div>
        {#if filter === 'all' || filter === 'timers'}
            {#each SAMPLE_TIMERS as tm (tm.rule)}{@render timerRow(tm, true)}{/each}
        {/if}
        {#each SAMPLE_AGENTS as a (a.id)}
            {#if filter === 'all' || filter === 'agents'}{@render agentRow(a, true)}{/if}
            {#if filter === 'all' || filter === 'shells'}
                {#each SAMPLE_SHELLS.filter((s) => s.owner === a.id) as s (s.id)}{@render shellRow(s, true, filter === 'all')}{/each}
            {/if}
        {/each}
        {#if filter === 'all' || filter === 'shells'}
            {#each SAMPLE_SHELLS.filter((s) => !s.owner) as s (s.id)}{@render shellRow(s, true, false)}{/each}
        {/if}
    {/if}
</div>

<style>
    .ccp {
        background: var(--oc-ground-page);
        font-size: var(--oc-fs-body, 12px);
        color: var(--oc-text-secondary);
    }

    .ccp-band {
        display: grid;
        grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.1fr) minmax(0, 1fr);
        box-shadow: inset 0 -1px 0 var(--oc-control-line);
    }

    .ccp-band > div {
        display: grid;
        grid-template-columns: max-content 1fr;
        align-content: start;
        gap: var(--oc-space-1) var(--oc-space-3);
        padding: 10px var(--oc-space-3);
    }

    .ccp-band > div + div {
        box-shadow: inset 1px 0 0 var(--oc-control-line);
    }

    .ccp-k,
    .ccp-ht {
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: 0.8px;
        line-height: 18px;
        text-transform: uppercase;
        color: var(--oc-text-muted);
    }

    .ccp-v {
        display: flex;
        align-items: center;
        gap: 6px;
        overflow: hidden;
        line-height: 18px;
        white-space: nowrap;
    }

    .ccp-model { color: var(--oc-orange); }
    .ccp-eff { color: var(--oc-cyan); }
    .ccp-dim { color: var(--oc-text-muted); }
    .ccp-c-ok { color: var(--oc-green); }
    .ccp-c-warn { color: var(--oc-yellow); }
    .ccp-c-info { color: var(--oc-cyan); }
    .ccp-bg-ok { background: var(--oc-green); }
    .ccp-bg-warn { background: var(--oc-yellow); }
    .ccp-bg-info { background: var(--oc-cyan); }

    .ccp-bar {
        display: inline-block;
        flex: none;
        width: 72px;
        height: 6px;
        overflow: hidden;
        border-radius: 1px;
        background: color-mix(in srgb, var(--oc-text-primary) 14%, transparent);
    }

    .ccp-gauge {
        display: inline-flex;
        flex: none;
        width: 72px;
    }

    .ccp-bar i {
        display: block;
        height: 100%;
    }

    .ccp-cols {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .ccp-col {
        min-width: 0;
    }

    .ccp-col + .ccp-col {
        box-shadow: inset 1px 0 0 var(--oc-control-line);
    }

    .ccp-h {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px var(--oc-space-3);
        box-shadow: inset 0 -1px 0 var(--oc-control-line);
    }

    .ccp-ht b {
        margin-left: var(--oc-space-1);
        color: var(--oc-text-primary);
        font-weight: normal;
    }

    .ccp-row {
        padding: 6px var(--oc-space-3);
        box-shadow: inset 0 -1px 0 var(--oc-control-line);
    }

    .ccp-r1 {
        display: flex;
        align-items: center;
        gap: var(--oc-space-2);
        min-width: 0;
        white-space: nowrap;
    }

    .ccp-r1 > * {
        flex: none;
    }

    .ccp-nm {
        flex: 0 1 auto;
        min-width: 7ch;
        overflow: hidden;
        text-overflow: ellipsis;
        color: var(--oc-text-bright);
    }

    .ccp-state {
        flex: 0 3 auto;
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        font-size: 11px;
        color: var(--oc-text-muted);
    }

    .ccp-tm {
        margin-left: auto;
        color: var(--oc-text-secondary);
    }

    .ccp-r2,
    .ccp-r3 {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--oc-text-muted);
    }

    .ccp-r3 {
        font-size: 11px;
        color: var(--oc-text-muted);
    }

    .ccp-indent {
        padding-left: 52px;
    }

    .ccp-more {
        padding: 6px var(--oc-space-3);
        color: var(--oc-text-muted);
    }

    .ccp-nest {
        position: relative;
        padding-left: 28px;
    }

    .ccp-nest::before {
        content: '';
        position: absolute;
        left: 16px;
        top: 0;
        bottom: 50%;
        width: 7px;
        border-bottom: 1px solid var(--oc-control-line-hi);
        border-left: 1px solid var(--oc-control-line-hi);
    }

    .ccp-kind {
        width: 44px;
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: 0.6px;
        text-transform: uppercase;
        color: var(--oc-text-muted);
    }

    .ccp-tabs {
        display: flex;
        align-items: center;
        gap: var(--oc-space-2);
        padding: var(--oc-space-2) var(--oc-space-3);
        box-shadow: inset 0 -1px 0 var(--oc-control-line);
    }

    .ccp-fill {
        flex: 1;
    }

    .ccp-tab {
        padding: 2px 10px;
        border: 1px solid var(--oc-control-line);
        border-radius: var(--oc-control-radius);
        background: transparent;
        color: var(--oc-text-secondary);
        font: inherit;
    }

    button.ccp-tab {
        cursor: pointer;
    }

    .ccp-tab[data-active='true'] {
        border-color: var(--oc-text-secondary);
        background: var(--oc-ground-hover);
        color: var(--oc-text-bright);
    }

    .ccp-tab b {
        margin-left: var(--oc-space-1);
        color: var(--oc-green);
        font-weight: normal;
    }

    .ccp-st {
        width: 7px;
        height: 7px;
        border-radius: 50%;
    }

    .ccp-st-work { background: var(--oc-green); }
    .ccp-st-wait { background: var(--oc-yellow); }

    .ccp-act {
        min-height: 0;
        cursor: default;
    }
</style>
