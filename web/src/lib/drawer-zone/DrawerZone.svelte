<script lang="ts">
  /* the glance area */
  import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import { onZoneContextMenu } from '../../opscenter/layout-editor/empty-space-menu.svelte';
  import { t } from '../i18n/index.svelte';
  import { drawerZone } from './zone-store.svelte';
  import { zoneDrag } from './zone-drag.svelte';
  import ZoneItem from './ZoneItem.svelte';
  import GlanceRow from './GlanceRow.svelte';
  import GlanceArea from './GlanceArea.svelte';
  import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
  import { widgetArea } from '../dynamic-tabs/widget-area.svelte';
  import { areaState as activeAreaState, drawnCards, glanceEntries as placedGlances } from './area-zones';

  $effect(() => {
    drawerZone.start();
  });

  const editing = $derived(layoutEditor.active);
  const tabId = $derived(sidebarTabs.active());
  const areaState = $derived(activeAreaState());
  const drawn = $derived(drawnCards());
  const glanceEntries = $derived(placedGlances());
  const openFull = (): void => widgetArea.set(tabId, 'full');
  const drop = $derived(!editing ? undefined : zoneDrag.index !== null ? 'aimed' : zoneDrag.carrying ? 'open' : undefined);
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="dz" oncontextmenu={onZoneContextMenu} data-drawer-zone data-editing={editing} data-area-state={areaState} data-drop={drop} aria-label={t('drawer_zone.label')}>
  {#if areaState === 'glance' && editing}
    <GlanceArea onopen={openFull} />
  {:else if areaState === 'glance'}
    <GlanceRow entries={glanceEntries} onopen={openFull} options />
  {:else if areaState === 'full'}
    <div class="dz-widgets" class:dz-widgets--editing={editing} data-zone-widgets>
      {#each drawn as entry, i (entry.key)}
        {#if editing && zoneDrag.index === i}<div class="dz-mark" data-zone-mark></div>{/if}
        <ZoneItem item={entry.item} manifest={entry.manifest} index={i} count={drawn.length} {editing} />
      {/each}
      {#if editing && zoneDrag.index === drawn.length && drawn.length > 0}<div class="dz-mark" data-zone-mark></div>{/if}
      {#if editing && drawn.length === 0}
        <p class="dz-empty" class:dz-empty--aimed={zoneDrag.index !== null} data-zone-empty>{t('drawer_zone.empty')}</p>
      {/if}
    </div>
    {#if editing}<GlanceArea onopen={openFull} />{/if}
  {/if}
</div>

<style>
  @layer components {
    .dz {
      min-width: 0;
    }

    /* the glance area */
    .dz-widgets--editing {
      position: relative;
    }

    .dz-widgets--editing::after {
      content: '';
      position: absolute;
      inset: 0;
      z-index: 60;
      border: var(--oc-border) dashed var(--oc-cyan);
      pointer-events: none;
    }

    .dz-empty {
      margin: 6px var(--oc-space-2) var(--oc-space-2);
      padding: 14px var(--oc-space-2);
      border: var(--oc-border) dashed var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      text-align: center;
    }

    .dz-empty--aimed {
      border-color: var(--oc-orange);
      color: var(--oc-orange);
    }

    .dz-mark {
      height: 2px;
      margin: 2px var(--oc-space-2);
      background: var(--oc-orange);
    }

    .dz[data-drop] > :not(.dz-mark) {
      background: color-mix(in oklab, var(--oc-cyan) 6%, transparent);
    }

    .dz[data-drop='aimed'] > :not(.dz-mark) {
      background: color-mix(in oklab, var(--oc-cyan) 12%, transparent);
      box-shadow: inset 0 0 0 var(--oc-border) var(--oc-cyan);
    }
  }
</style>
