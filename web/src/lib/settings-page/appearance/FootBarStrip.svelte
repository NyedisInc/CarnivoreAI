<!-- hidden -->
<script lang="ts">
    import Icon from '../../../opscenter/ui/Icon.svelte';
    import LimitGauge from '../../../opscenter/ui/LimitGauge.svelte';
    import type { Translate } from '../../sessions/types';
    import { footBarItems } from '../foot-bar-items-store.svelte';
    import { footBarOrder, type FootBarOrderId } from '../foot-bar-order-store.svelte';
    import { SAMPLE_METERS, SAMPLE_SESSION, leadingMeter, sampleScale, samplePaceState } from './samples';

    interface Props {
        layout: 'a' | 'b' | 'c';
        t: Translate;
    }

    const { layout, t }: Props = $props();

    const visible = $derived(footBarOrder.value.filter((id) => footBarItems.effective(id)));
    const lead = $derived(layout === 'c' ? leadingMeter(visible) : null);
    const rest = $derived(visible.filter((id) => id !== lead));
    const scopes = $derived(
        (['session', 'account'] as const)
            .map((scope) => ({ scope, ids: visible.filter((id) => SAMPLE_METERS[id].scope === scope) }))
            .filter((g) => g.ids.length > 0),
    );
    const showModel = $derived(footBarItems.effective('model'));
    const showEffort = $derived(showModel && footBarItems.effective('effort'));
    const hasWork = $derived(
        footBarItems.effective('agents') || footBarItems.effective('shells') || footBarItems.effective('timers'),
    );

    function meterName(id: FootBarOrderId): string {
        return SAMPLE_METERS[id].short;
    }

    function fit(node: HTMLElement): { destroy: () => void } {
        const run = (): void => {
            for (let i = 1; i <= 6; i++) node.classList.remove(`f${i}`);
            for (let level = 1; level <= 6 && node.scrollWidth > node.clientWidth + 1; level++) {
                for (let j = 1; j <= level; j++) node.classList.add(`f${j}`);
            }
        };
        run();
        const resize = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(run);
        resize?.observe(node);
        const mutate = typeof MutationObserver === 'undefined' ? null : new MutationObserver(run);
        mutate?.observe(node, { childList: true, subtree: true, characterData: true });
        return {
            destroy: () => {
                resize?.disconnect();
                mutate?.disconnect();
            },
        };
    }
</script>

{#snippet meter(id: FootBarOrderId, mode: 'bars' | 'text' | 'lead' | 'bare')}
    {@const m = SAMPLE_METERS[id]}
    {#if mode === 'bare'}
        <span class="fbs-piece fbs-bare" data-meter={id}>{meterName(id)} {m.pct}%</span>
    {:else}
        <span class="fbs-piece" data-meter={id}>
            {#if mode === 'lead'}<span class="fbs-dot fbs-bg-{m.tone}"></span>{/if}
            <span class="fbs-lbl">{meterName(id)}</span>
            {#if mode !== 'text'}
                {#if m.elapsedPct !== undefined}
                    <span class="fbs-gauge"><LimitGauge variant="fill" pct={m.pct} scale={sampleScale(m.tone)} paceElapsedPct={m.elapsedPct} paceState={samplePaceState(m)} meterText={`${m.short} ${m.pct}%`} height={6} ariaHidden /></span>
                {:else}
                    <span class="fbs-bar"><i class="fbs-bg-{m.tone}" style:width="{m.pct}%"></i></span>
                {/if}
            {/if}
            <span class="fbs-c-{m.tone}">{m.pct}%</span>
            {#if id === 'context'}
                <span class="fbs-dim fbs-x-ctx">{m.detail}</span>
            {:else}
                <span class="fbs-dim {id === 'window_5h' ? 'fbs-x-5h' : 'fbs-x-7d'}"><Icon name="reset" size={11} /> {m.reset}</span>
            {/if}
        </span>
    {/if}
{/snippet}

{#snippet model()}
    <span class="fbs-grp" class:fbs-tint={layout === 'b'}>
        <span class="fbs-piece fbs-model" data-item="model">{SAMPLE_SESSION.model}</span>
        {#if showEffort}<span class="fbs-piece fbs-eff" data-item="effort">{SAMPLE_SESSION.effort}</span>{/if}
    </span>
{/snippet}

<div class="fbs" data-layout={layout} aria-hidden="true" use:fit>
    {#if showModel}
        {@render model()}
        {#if visible.length}<span class="fbs-sep"></span>{/if}
    {/if}
    {#if layout === 'a'}
        {#each visible as id (id)}{@render meter(id, 'bars')}{/each}
    {:else if layout === 'b'}
        {#each scopes as group, gi (group.scope)}
            {#if gi > 0}<span class="fbs-sep"></span>{/if}
            <span class="fbs-grp">
                <span class="fbs-cap">{t(`settings.footbarpreview.scope.${group.scope}`)}</span>
                {#each group.ids as id (id)}{@render meter(id, 'text')}{/each}
            </span>
        {/each}
    {:else}
        {#if lead}{@render meter(lead, 'lead')}{/if}
        {#if rest.length}
            {#if lead}<span class="fbs-sep"></span>{/if}
            <span class="fbs-grp fbs-loose">{#each rest as id (id)}{@render meter(id, 'bare')}{/each}</span>
        {/if}
    {/if}
    <span class="fbs-fill"></span>
    {#if hasWork}
        {#if footBarItems.effective('agents')}
            <span class="fbs-piece" data-item="agents"><span class="fbs-lbl">ag</span><b class="fbs-c-ok">{SAMPLE_SESSION.agents}</b></span>
        {/if}
        {#if footBarItems.effective('shells')}
            <span class="fbs-piece" data-item="shells"><span class="fbs-lbl">sh</span><b class="fbs-c-ok">{SAMPLE_SESSION.shells}</b></span>
        {/if}
        {#if footBarItems.effective('timers')}
            <span class="fbs-piece" data-item="timers">
                <Icon name="clock" size={11} /><b>{SAMPLE_SESSION.timers}</b>
                <span class="fbs-lbl fbs-x-full">{t('settings.footbarpreview.next')}</span>
                <span>{SAMPLE_SESSION.nextTimer}</span>
            </span>
        {/if}
    {/if}
</div>

<style>
    .fbs {
        display: flex;
        align-items: center;
        gap: var(--oc-space-3);
        height: 30px;
        padding: 0 var(--oc-space-3);
        background: var(--oc-ground-titlerow);
        white-space: nowrap;
        overflow: hidden;
        font-size: var(--oc-fs-body, 12px);
        color: var(--oc-text-secondary);
    }

    .fbs-grp,
    .fbs-piece {
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }

    .fbs-loose {
        gap: var(--oc-space-3);
    }

    .fbs-sep {
        flex: none;
        width: 1px;
        height: 12px;
        background: var(--oc-control-line-hi);
    }

    .fbs-fill {
        flex: 1;
    }

    .fbs-lbl,
    .fbs-dim {
        color: var(--oc-text-muted);
    }

    .fbs-model {
        color: var(--oc-orange);
    }

    .fbs-eff {
        color: var(--oc-cyan);
    }

    .fbs-bare {
        color: var(--oc-text-muted);
    }

    .fbs-tint {
        padding: 2px var(--oc-space-2);
        border-radius: 1px;
        background: color-mix(in srgb, var(--oc-orange) 14%, transparent);
    }

    .fbs-cap {
        font-size: var(--oc-fs-micro, 10px);
        letter-spacing: 0.8px;
        text-transform: uppercase;
        color: var(--oc-text-muted);
    }

    .fbs-bar {
        display: inline-block;
        width: 56px;
        height: 6px;
        overflow: hidden;
        border-radius: 1px;
        background: color-mix(in srgb, var(--oc-text-primary) 14%, transparent);
    }

    .fbs-gauge {
        display: inline-flex;
        width: 56px;
    }

    .fbs-bar i {
        display: block;
        height: 100%;
    }

    .fbs-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
    }

    .fbs-c-ok { color: var(--oc-green); }
    .fbs-c-warn { color: var(--oc-yellow); }
    .fbs-c-info { color: var(--oc-cyan); }
    .fbs-bg-ok { background: var(--oc-green); }
    .fbs-bg-warn { background: var(--oc-yellow); }
    .fbs-bg-info { background: var(--oc-cyan); }

    .fbs:global(.f1) .fbs-x-7d,
    .fbs:global(.f2) .fbs-x-ctx,
    .fbs:global(.f4) .fbs-x-5h,
    .fbs:global(.f5) .fbs-bar,
    .fbs:global(.f5) .fbs-gauge,
    .fbs:global(.f6) .fbs-eff,
    .fbs:global(.f3) .fbs-x-full {
        display: none;
    }

    .fbs:global(.f2) .fbs-cap {
        display: none;
    }
</style>
