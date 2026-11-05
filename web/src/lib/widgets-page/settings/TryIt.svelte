
<script lang="ts">
    import { Button } from '../../base';
    import type { Translate } from '../../sessions/types';
    import { railStores } from '../../session-rail/rail-store.svelte';
    import { RAIL_EDGES, type RailEdge } from '../../session-rail/rail-model';
    import { widgetBars } from '../../widget-bars/bar-settings.svelte';
    import { barThickness, HANDLE_PX } from '../../widget-bars/bar-size';
    import { barOut, inFlow, showsHandle, showsPin, type BarVisual } from '../../widget-bars/bar-state';
    import BarPin from '../../widget-bars/BarPin.svelte';
    import ZoneHandle from '../../zone-shell/ZoneHandle.svelte';
    import { nameLetters } from '../../widget-bars/pinned-scope';
    import { barName } from '../bar-run';
    import MockBar from './MockBar.svelte';
    import MockLayout from './MockLayout.svelte';
    import { STAGE_W, mockKeys, type MockKey } from './mock-model';
    import { PANEL_PX, TryScene } from './try-scene.svelte';

    interface Props { t: Translate }
    const { t }: Props = $props();

    const CLICK_SLOP_PX = 4;
    const KEY_STEP_PX = 20;

    const scene = new TryScene();
    $effect(() => () => scene.destroy());

    const view = $derived(widgetBars.view);
    const keys = $derived<Record<RailEdge, MockKey[]>>({ side: mockKeys(railStores.side.items, t), bottom: mockKeys(railStores.bottom.items, t) });
    const looks = $derived({ side: scene.visual('side', view, keys.side.length > 0), bottom: scene.visual('bottom', view, keys.bottom.length > 0) });
    const agentName = (agent: 0 | 1): string => t(agent === 0 ? 'widgets.settings.try.agent_one' : 'widgets.settings.try.agent_two');

    function trackPx(edge: RailEdge): number {
        const look: BarVisual = looks[edge];
        if (look === 'absent') return 0;
        return inFlow(look) ? barThickness(edge, view[edge].size) : HANDLE_PX;
    }

    const zone = (edge: RailEdge) => ({
        onpointerenter: () => scene.enter(edge), onpointerleave: () => scene.leave(edge),
        onfocusin: () => scene.focusIn(edge), onfocusout: () => scene.focusOut(edge),
    });

    function letterOf(edge: RailEdge, key: string): string {
        const other = scene.otherPin(edge, key);
        return other === null ? '' : (nameLetters(agentName(other))[0] ?? '');
    }
    function nameOf(edge: RailEdge, one: MockKey): string {
        const other = scene.otherPin(edge, one.key);
        return other === null ? one.title : t('widget_bars.key_pinned', { widget: one.title, agent: agentName(other) });
    }

    let drag: { id: number; start: number; from: number; moved: boolean; k: number } | null = null;
    const along = (event: PointerEvent, edge: RailEdge): number => (edge === 'side' ? event.clientX : event.clientY);

    function down(event: PointerEvent, edge: RailEdge): void {
        if (event.button !== 0) return;
        const stage = (event.currentTarget as HTMLElement).closest('.wp-mock__stage');
        const k = stage ? stage.getBoundingClientRect().width / STAGE_W : 1;
        drag = { id: event.pointerId, start: along(event, edge), from: scene.edges[edge].panelPx, moved: false, k: k > 0 ? k : 1 };
        try { (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId); } catch {  }
        event.preventDefault();
    }
    function move(event: PointerEvent, edge: RailEdge): void {
        if (!drag || event.pointerId !== drag.id) return;
        const rendered = drag.start - along(event, edge);
        if (!drag.moved && Math.abs(rendered) < CLICK_SLOP_PX) return;
        drag.moved = true;
        scene.resize(edge, drag.from + rendered / drag.k);
    }
    function up(event: PointerEvent, edge: RailEdge): void {
        if (!drag || event.pointerId !== drag.id) return;
        if (!drag.moved) scene.togglePin(edge);
        drag = null;
    }
    function edgeKey(event: KeyboardEvent, edge: RailEdge): void {
        const grow = edge === 'side' ? 'ArrowLeft' : 'ArrowUp';
        const shrink = edge === 'side' ? 'ArrowRight' : 'ArrowDown';
        const now = scene.edges[edge].panelPx;
        if (event.key === grow) scene.resize(edge, now + KEY_STEP_PX);
        else if (event.key === shrink) scene.resize(edge, now - KEY_STEP_PX);
        else if (event.key === 'Home') scene.resize(edge, PANEL_PX[edge].initial);
        else if (event.key === 'Enter' || event.key === ' ') scene.togglePin(edge);
        else return;
        event.preventDefault();
        event.stopPropagation();
    }
</script>

<div class="wp-try">
    <MockLayout sidePx={trackPx('side')} bottomPx={trackPx('bottom')} label={t('widgets.settings.try.label')} {t}>
        {#each RAIL_EDGES as edge (edge)}
            {@const look = looks[edge]}
            {@const at = scene.edges[edge]}
            {@const open = keys[edge].find((one) => one.key === at.openKey)}
            {#if look !== 'absent'}
                <div class="wp-try__layer" data-edge={edge} data-state={look} style:--mock-handle="{HANDLE_PX}px" {...zone(edge)}>
                    {#if showsHandle(look)}
                        <div class="wp-try__handle wp-try__handle--{edge}"><ZoneHandle {edge} expanded={barOut(look)} peek={{ onpress: () => scene.enter(edge) }} /></div>
                    {/if}
                    {#if barOut(look)}
                        <MockBar {edge} size={view[edge].size} keys={keys[edge]} label={barName(edge, t)} open={at.openKey ?? ''} onPress={(key) => scene.press(edge, key)}
                            badge={(key) => letterOf(edge, key)} nameOf={(one) => nameOf(edge, one)}>
                            {#snippet end()}{#if showsPin(look)}<BarPin {edge} />{/if}{/snippet}
                        </MockBar>
                    {/if}
                    {#if look === 'held' && open}
                        <div class="wp-try__panel wp-try__panel--{edge}" style:--panel-px="{at.panelPx}px" style:--panel-bar="{barThickness(edge, view[edge].size)}px">
                            
                            <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
                            <div class="wp-try__pin" class:wp-try__pin--on={at.pinnedOn !== null} role="separator" tabindex="0" data-try-pin={edge}
                                aria-orientation={edge === 'side' ? 'vertical' : 'horizontal'} aria-valuemin={PANEL_PX[edge].min} aria-valuemax={PANEL_PX[edge].max} aria-valuenow={at.panelPx}
                                aria-label={at.pinnedOn !== null ? t('widget_bars.edge_pinned', { agent: agentName(at.pinnedOn) }) : t('widget_bars.edge')}
                                onpointerdown={(event) => down(event, edge)} onpointermove={(event) => move(event, edge)} onpointerup={(event) => up(event, edge)} onkeydown={(event) => edgeKey(event, edge)}><span class="wp-try__pin-line"></span></div>
                            <div class="wp-try__panel-body"><span class="wp-try__panel-title">{open.title}</span><span class="wp-try__panel-note">{t('widgets.settings.try.sample')}</span></div>
                        </div>
                    {/if}
                </div>
            {/if}
        {/each}
    </MockLayout>

    <div class="wp-try__agents">
        <span class="wp-try__active" role="status">{t('widgets.settings.try.active', { agent: agentName(scene.agent) })}</span>
        <Button size="sm" data-k="try-switch" onclick={() => scene.switchAgent()}>{t('widgets.settings.try.switch_agent')}</Button>
    </div>
</div>
