<script lang="ts">
  import CellHost from '../opscenter/CellHost.svelte';
  import ZoneItem from '../lib/drawer-zone/ZoneItem.svelte';
  import GlanceRow from '../lib/drawer-zone/GlanceRow.svelte';
  import { drawerZone } from '../lib/drawer-zone/zone-store.svelte';
  import { zoneItemKey, type ZoneItem as ZoneItemModel } from '../lib/drawer-zone/zone-model';
  import { railStores } from '../lib/session-rail/rail-store.svelte';
  import { singleSection } from '../lib/session-rail/rail-sections';
  import PlacementBody from '../lib/zone-shell/PlacementBody.svelte';
  import { readKeyMenuMessage } from './key-menu-message';
  import RailKeyMenu from '../lib/widget-menu/RailKeyMenu.svelte';
  import { createLayoutStore } from '../opscenter/engine/layout.svelte';
  import { HEADER_OPTION } from '../opscenter/shell/widget-head';
  import { manifestById } from '../opscenter/widgets/core-manifests';
  import type { HarnessWidget } from './catalog';
  import type { StandardSize } from '../opscenter/widgets/standard-sizes';
  import type { FitZone } from '../opscenter/widgets/types';

  let { widget, zone, size, dock = null }: { widget: HarnessWidget; zone: FitZone; size: StandardSize; dock?: 'side' | 'bottom' | null } = $props();

  const store = createLayoutStore(zone === 'terminal' ? 'terminal' : 'home');
  if (zone !== 'drawer' && new URLSearchParams(location.search).get('header') === 'off') store.setHeaderShown(widget.slot, false);
  const manifest = $derived(manifestById(widget.manifest));
  if (zone === 'drawer') {
    const headerParam = new URLSearchParams(location.search).get('header');
    const options = headerParam === 'on' || headerParam === 'off' ? { [HEADER_OPTION]: headerParam === 'on' } : undefined;
    const seed: ZoneItemModel = {
      widget: widget.manifest,
      look: null,
      ...(widget.target ? { target: widget.target } : {}),
      ...(options ? { options } : {}),
    };
    if (dock) railStores[dock].stored = singleSection([seed]);
    else drawerZone.stored = [seed];
  }
  let keyMenuAt = $state<{ x: number; y: number } | null>(null);
  let keyMenuSpot = $state<HTMLElement | null>(null);
  function onRailContextMenu(event: MouseEvent): void {
    if (event.defaultPrevented || (event.target as Element | null)?.closest('input, textarea, [contenteditable]')) return;
    event.preventDefault();
    keyMenuAt = { x: event.clientX, y: event.clientY };
  }
  $effect(() => {
    if (!dock) return;
    const onMessage = (event: MessageEvent): void => {
      const asked = event.origin === location.origin && event.source === window.parent ? readKeyMenuMessage(event.data) : null;
      if (asked) keyMenuAt = { x: asked.x, y: asked.y };
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  });
  const zoneItem = $derived(dock ? railStores[dock].items[0]! : drawerZone.items[0]!);
  const style = $derived(`width:${size.w}px;${size.h === null ? '' : `height:${size.h}px;`}`);
</script>

<div class="wh-stage" data-zone={zone} data-size={size.name}>
  {#if zone === 'drawer' && dock}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="wh-rail-body" data-harness-cell data-dock={dock} {style} oncontextmenu={onRailContextMenu}>
      {#if manifest}<PlacementBody host="rail" source={railStores[dock]} {manifest} target={widget.target} edge={dock} options={zoneItem.options} placementKey={zoneItemKey(zoneItem)} />{/if}
    </div>
    {#if keyMenuAt}
      <span class="wh-menu-spot" bind:this={keyMenuSpot} style:left={`${keyMenuAt.x}px`} style:top={`${keyMenuAt.y}px`} aria-hidden="true"></span>
      <RailKeyMenu edge={dock} itemKey={zoneItemKey(zoneItem)} anchor={keyMenuSpot} onClose={() => (keyMenuAt = null)} />
    {/if}
  {:else if zone === 'drawer'}
    <div class="wh-cell wh-cell--drawer" data-harness-cell {style}>
      {#if manifest && size.name === 'glance'}
        <GlanceRow
          entries={[{ key: widget.manifest, widget: widget.manifest, manifest, options: widget.target ? { target: widget.target } : {} }]}
          onopen={() => undefined}
        />
      {:else if manifest}
        <ZoneItem item={zoneItem} {manifest} index={0} count={1} editing={false} />
      {/if}
    </div>
  {:else if zone === 'popout'}
    <div id="popout-screen">
      <div class="oc-cellslot wh-cell" data-harness-cell {style}><CellHost id={widget.slot} {store} /></div>
    </div>
  {:else}
    <div class="oc-cellslot wh-cell" data-harness-cell {style}><CellHost id={widget.slot} {store} /></div>
  {/if}
</div>

<style>
  .wh-stage {
    display: inline-block;
    padding: 16px;
    background: var(--oc-ground-page);
  }
  .wh-cell--drawer {
    overflow: hidden;
  }
  .wh-menu-spot {
    position: fixed;
    width: 0;
    height: 0;
    pointer-events: none;
  }
  @layer components {
    .wh-rail-body {
      display: flex;
      flex-direction: column;
      min-width: 0;
      min-height: 0;
      overflow: hidden;
      border-radius: 0;
      background: var(--oc-ground-panel);
      container: oc-head / inline-size;
    }
  }
</style>
