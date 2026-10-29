<script lang="ts">
  import IconButton from '../base/IconButton.svelte';
  import Segmented from '../base/Segmented.svelte';
  import LedgerCell from '../../opscenter/cells/ledger/Cell.svelte';
  import { META } from '../../opscenter/engine/meta';
  import { t } from '../i18n/index.svelte';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import { viewOfPlacement, viewsOf } from '../../opscenter/widgets/views';
  import { placementHead } from '../../opscenter/widgets/placement-options';
  import { drawerZone } from './zone-store.svelte';
  import { lookOf, zoneItemKey, type ZoneItem as Item } from './zone-model';
  import { beginZoneItemDrag } from './zone-drag.svelte';
  import PlacementBody from '../zone-shell/PlacementBody.svelte';
  import ZoneShell from '../zone-shell/ZoneShell.svelte';
  import { untrack } from 'svelte';
  import { drawerCardZone } from './area-zones';

  let {
    item,
    manifest,
    index,
    count,
    editing,
  }: { item: Item; manifest: WidgetManifest; index: number; count: number; editing: boolean } = $props();

  const key = $derived(zoneItemKey(item));
  const title = $derived(placementHead(manifest.id, item.options)?.title ?? t(manifest.titleKey));
  const look = $derived(lookOf(manifest, item));
  const looks = $derived(manifest.looks?.names ?? []);
  const views = $derived(viewsOf(manifest));
  const view = $derived(viewOfPlacement(manifest, item.view)?.id ?? null);

  const compactLedger = $derived(manifest.id === 'core.ledger' && look !== 'full');

  const zone = drawerCardZone(untrack(() => zoneItemKey(item)));
  const tabKey = untrack(() => zoneItemKey(item));
  const watchOnScreen = zone.watch(tabKey);

  function onHandleDown(event: PointerEvent): void {
    beginZoneItemDrag(event.currentTarget as HTMLElement, event, key, {
      onDrop: (to) => drawerZone.move(key, to),
    });
  }
</script>

<ZoneShell {zone} bare>
  {#snippet tab()}
    <div class="dz-item" data-zone-item={key} data-look={look ?? ''} class:dz-item--editing={editing} data-zone-pane={tabKey} data-zone-visible={zone.visibility(tabKey)} {@attach watchOnScreen}>
      {#if editing}
        <div class="dz-strip" role="group" aria-label={title}>
          <IconButton label={t('drawer_zone.drag', { title })} variant="quiet" icon="grip" data-zone-handle onpointerdown={onHandleDown} />
          <span class="dz-name">{title}</span>
          {#if views.length > 0}
            <Segmented label={t('drawer_zone.view')} value={view ?? ''} size="sm"
              options={views.map((one) => ({ value: one.id, label: t(one.titleKey), attrs: { 'data-zone-view': one.id } }))}
              onchange={(next) => drawerZone.setView(key, next)} />
          {/if}
          {#if looks.length > 1}
            <Segmented label={t('drawer_zone.look')} value={look ?? ''} size="sm"
              options={looks.map((name) => ({ value: name, label: t(`drawer_zone.look.${name}`), attrs: { 'data-zone-look': name } }))}
              onchange={(next) => drawerZone.setLook(key, next as typeof looks[number])} />
          {/if}
          <IconButton label={t('drawer_zone.up', { title })} variant="quiet" data-zone-up disabled={index === 0}
            onclick={() => drawerZone.step(key, -1)}>&#8593;</IconButton>
          <IconButton label={t('drawer_zone.down', { title })} variant="quiet" data-zone-down disabled={index === count - 1}
            onclick={() => drawerZone.step(key, 1)}>&#8595;</IconButton>
          <IconButton label={t('drawer_zone.remove', { title })} variant="close" data-zone-remove
            onclick={() => drawerZone.remove(key)}>&#215;</IconButton>
        </div>
      {/if}
      {#if compactLedger}
        <LedgerCell drawer width={0} height={0} meta={META.ledger} instance={key} phone={false} limit={null} />
      {:else}
        <PlacementBody host="drawer" source={drawerZone} placementKey={key} {manifest} target={item.target ?? null} view={item.view ?? null} instance={item.instance ?? null} options={item.options} />
      {/if}
    </div>
  {/snippet}
</ZoneShell>

<style>
  @layer components {
    .dz-item {
      min-width: 0;
    }

    .dz-strip {
      --oc-ibtn-size: 22px;
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      margin: 6px var(--oc-space-2) 0;
      padding: 2px var(--oc-space-1);
      border: var(--oc-border) dashed var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .dz-name {
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      color: var(--oc-orange);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .dz-strip :global([data-zone-handle]) {
      cursor: grab;
      touch-action: none;
    }
  }
</style>
