<script lang="ts">
  import { flushSync, onDestroy } from 'svelte';
  import { onZoneContextMenu } from '../../opscenter/layout-editor/empty-space-menu.svelte';
  import { layoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import { manifestById } from '../../opscenter/widgets/core-manifests';
  import { registerDropHost } from '../motion-grid';
  import { zoneDrag } from './zone-drag.svelte';
  import { glanceDrag } from './glance-drag.svelte';
  import { mountStack, scrollParent, type Stack } from '../zone-motion/stack-motion';
  import IconButton from '../base/IconButton.svelte';
  import { t } from '../i18n/index.svelte';
  import { drawerZone } from './zone-store.svelte';
  import { addItem } from './zone-model';
  import { ZONE_HEIGHT_CAP, ZONE_HEIGHT_MIN, zoneHeightOf } from '../../opscenter/widgets/placement-options';
  import ZoneItem from './ZoneItem.svelte';
  import GlanceRow from './GlanceRow.svelte';
  import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
  import { widgetArea } from '../dynamic-tabs/widget-area.svelte';
  import { areaState as activeAreaState, drawnCards, glanceEntries as placedGlances } from './area-zones';

  const GRAB = '.oc-frame-title, .oc-frame-strip, [data-widget-head], [data-zone-head], [data-motion-grab]';
  const ZONE_ID = 'zone:drawer';
  const PENDING_PX = 56;

  $effect(() => {
    drawerZone.start();
  });

  const tabId = $derived(sidebarTabs.active());
  const areaState = $derived(activeAreaState());
  const drawn = $derived(drawnCards());
  const glanceEntries = $derived(placedGlances());
  const openFull = (): void => widgetArea.set(tabId, 'full');

  let pending = $state<{ id: string; kind: string } | null>(null);
  const cells = $derived([
    ...drawn.map((entry) => ({ id: entry.key, entry, kind: null as string | null })),
    ...(pending ? [{ id: pending.id, entry: null, kind: pending.kind }] : []),
  ]);
  const order = $derived(cells.map((cell) => cell.id));

  let root = $state<HTMLElement | null>(null);
  let notice = $state('');

  const drop = $derived(zoneDrag.index !== null || glanceDrag.index !== null ? 'aimed' : zoneDrag.carrying || glanceDrag.carrying ? 'open' : undefined);

  function markAt(index: number | null, selector: string, axis: 'x' | 'y'): number | null {
    if (index === null || !root) return null;
    const near = axis === 'y' ? 'top' : 'left';
    const far = axis === 'y' ? 'bottom' : 'right';
    const base = root.getBoundingClientRect()[near];
    const items = [...root.querySelectorAll<HTMLElement>(selector)];
    const at = items[index];
    if (at) return at.getBoundingClientRect()[near] - base;
    const last = items[items.length - 1];
    return (last ? last.getBoundingClientRect()[far] : root.getBoundingClientRect()[far]) - base;
  }
  const zoneMark = $derived(areaState === 'full' ? markAt(zoneDrag.index, '[data-zone-item]', 'y') : null);
  const glanceMark = $derived(areaState === 'glance' ? markAt(glanceDrag.index, '[data-glance-row-place]', 'x') : null);
  let stack: Stack | null = null;
  let stackEl: HTMLElement | null = null;

  function ensure(node: HTMLElement): Stack {
    const column = node.closest<HTMLElement>('[data-zone-widgets]') ?? (node.parentElement as HTMLElement);
    if (stack && stackEl === column) return stack;
    stack?.destroy();
    stackEl = column;
    stack = mountStack(column, {
      axis: 'y',
      order: () => order,
      grab: GRAB,
      place: (id, index, external) => {
        if (external && pending) {
          const kind = pending.kind;
          pending = null;
          drawerZone.add(kind, index);
        } else if (!external) drawerZone.move(id, index);
      },
      resize: {
        limits: () => ({ min: ZONE_HEIGHT_MIN, max: Math.max(ZONE_HEIGHT_MIN, Math.min(ZONE_HEIGHT_CAP, scrollParent(column)?.clientHeight || window.innerHeight)) }),
        commit: (id, h) => {
          if (drawerZone.setHeight(id, h)) return;
          notice = t('drawer_zone.height_full');
          stack?.sync();
        },
      },
      label: (id) => {
        const cell = cells.find((one) => one.id === id);
        const manifest = cell?.entry?.manifest ?? (cell?.kind ? manifestById(cell.kind) : undefined);
        return manifest ? t(manifest.titleKey) : id;
      },
    });
    stack.handle.on('settle', () => {
      if (pending) pending = null;
    });
    return stack;
  }

  function cell(node: HTMLElement, id: string): { update(id: string): void; destroy(): void } {
    return ensure(node).cell(node, id);
  }

  $effect(() => {
    void order;
    stack?.sync();
  });

  const takes = (kind: string): boolean => !!manifestById(kind) && addItem(drawerZone.items, kind).length !== drawerZone.items.length;

  $effect(() => {
    if (!root) return;
    return registerDropHost(root, {
      id: ZONE_ID,
      takes,
      accept(kind, ev) {
        if (!takes(kind)) return false;
        if (areaState !== 'full') {
          openFull();
          flushSync();
        }
        pending = { id: `pending:${kind}`, kind };
        flushSync();
        const width = stackEl?.clientWidth ?? 0;
        const ok = !!stack?.handle.beginExternal({ id: `pending:${kind}`, rect: { x: 0, y: 0, w: width, h: PENDING_PX }, grab: { x: Math.min(40, width / 2), y: PENDING_PX / 2 } }, ev);
        if (!ok) pending = null;
        return ok;
      },
      add: (kind) => takes(kind) && drawerZone.add(kind),
    });
  });

  const openAdd = (): void => {
    document.dispatchEvent(new CustomEvent('oc-widget-drawer-open', { detail: { surface: ZONE_ID } }));
  };

  onDestroy(() => {
    stack?.destroy();
    stack = null;
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="dz" bind:this={root} oncontextmenu={onZoneContextMenu} data-drawer-zone data-drop={drop} data-area-state={areaState} aria-label={t('drawer_zone.label')}>
  {#if areaState === 'glance'}
    <GlanceRow entries={glanceEntries} onopen={openFull} options />
    {#if glanceMark !== null}<div class="dz-gmark" style:left="{glanceMark}px" data-glance-mark></div>{/if}
  {:else if areaState === 'full'}
    {#if layoutEditor.active}
      <div class="dz-head" data-zone-head>
        <IconButton label={t('awe5.zone.add')} variant="quiet" icon="plus" data-zone-add onclick={openAdd} />
      </div>
    {/if}
    <div class="dz-widgets" data-zone-widgets>
      <div class="dz-cells">
      {#each cells as one (one.id)}
        <div class="dz-cell" use:cell={one.id}>
          <div class="dz-cell__body" style:height={one.entry && zoneHeightOf(one.entry.item.options) !== null ? `${zoneHeightOf(one.entry.item.options)}px` : undefined} data-sized={one.entry && zoneHeightOf(one.entry.item.options) !== null ? '' : undefined}>
            {#if one.entry}
              <ZoneItem item={one.entry.item} manifest={one.entry.manifest} />
            {:else}
              <p class="dz-empty dz-pending" data-zone-pending>{one.kind && manifestById(one.kind) ? t(manifestById(one.kind)!.titleKey) : ''}</p>
            {/if}
          </div>
          {#if one.entry}<div class="motion-handle motion-handle--s" data-stack-resize></div>{/if}
        </div>
      {/each}
      </div>
    </div>
    <span class="dz-notice" role="status">{notice}</span>
    {#if zoneMark !== null}<div class="dz-mark" style:top="{zoneMark}px" data-zone-mark></div>{/if}
    {#if drawn.length === 0 && !pending}
      <p class="dz-empty" data-zone-empty>{t('drawer_zone.empty')}</p>
    {/if}
  {/if}
</div>

<style>
  @layer components {
    .dz {
      position: relative;
      min-width: 0;
    }

    .dz-mark {
      position: absolute;
      left: var(--oc-space-2);
      right: var(--oc-space-2);
      height: 2px;
      background: var(--oc-orange);
      pointer-events: none;
    }

    .dz-gmark {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 2px;
      background: var(--oc-orange);
      pointer-events: none;
    }

    .dz[data-drop] {
      background: color-mix(in oklab, var(--oc-cyan) 6%, transparent);
    }

    .dz[data-drop='aimed'] {
      background: color-mix(in oklab, var(--oc-cyan) 12%, transparent);
      box-shadow: inset 0 0 0 var(--oc-border) var(--oc-cyan);
    }

    .dz-head {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: var(--oc-space-1);
      padding: 0 var(--oc-space-2);
      box-shadow: 0 1px 0 var(--oc-line-panel);
    }

    .dz-widgets {
      position: relative;
    }

    .dz-cells {
      display: contents;
    }

    .dz-cell {
      overflow: clip;
    }

    .dz-cell__body[data-sized] {
      overflow: auto;
    }

    .dz-cell > :global(.motion-handle--s) {
      right: 0 !important;
      bottom: 0 !important;
      height: 8px !important;
    }

    .dz-cell > :global(.motion-handle--s::after) {
      top: 3px !important;
    }

    .dz-notice {
      position: absolute;
      width: 1px;
      height: 1px;
      margin: -1px;
      overflow: hidden;
      clip-path: inset(50%);
    }

    .dz-cell__body {
      display: flow-root;
      min-width: 0;
    }

    .dz-cell:has(~ .dz-cell) :global([data-zone-card]) {
      margin-bottom: 0;
      border-bottom-left-radius: 0;
      border-bottom-right-radius: 0;
    }

    .dz-cell ~ .dz-cell :global([data-zone-card]) {
      margin-top: 0;
      border-top-width: 0;
      border-top-left-radius: 0;
      border-top-right-radius: 0;
    }

    .dz-pending {
      border-color: var(--oc-orange);
      color: var(--oc-orange);
    }

    @media (max-width: 700px) {
      .dz-head {
        display: none;
      }
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
  }
</style>
