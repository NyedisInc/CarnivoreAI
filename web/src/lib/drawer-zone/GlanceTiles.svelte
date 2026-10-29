<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import WidgetIcon from '../../opscenter/ui/WidgetIcon.svelte';
  import TabKey, { keyFace } from '../zone-shell/TabKey.svelte';
  import type { WidgetManifest } from '../../opscenter/widgets/types';
  import { GLANCE_TILE_HEIGHT_PX, GLANCE_TILE_WIDTH_PX, glanceFor, type PlacementOptions } from './glance';
  import './glances';

  let {
    placement,
    widget,
    manifest,
    options = {},
    onopen,
    onmenu,
  }: {
    placement: string;
    widget: string;
    manifest: WidgetManifest;
    options?: PlacementOptions;
    onopen: () => void;
    onmenu?: (anchor: HTMLElement) => void;
  } = $props();

  const NO_WORDS = keyFace({});

  const menu = $derived(onmenu ? (_id: string, anchor: HTMLElement) => onmenu(anchor) : undefined);

  const glance = $derived(glanceFor(widget));
  const tiles = $derived(glance ? glance.tiles(options) : []);
</script>

{#if glance && tiles.length > 0}
  {@const Tile = glance.component}
  {#each tiles as tile (tile.key)}
    <TabKey
      id={tile.key}
      shape="tile"
      variant="glance"
      frame
      face={NO_WORDS}
      iconPx={14}
      quiet
      state={null}
      active={false}
      tabbable={null}
      style={`width: ${GLANCE_TILE_WIDTH_PX}px; height: ${glance.height}px;`}
      attrs={{ 'data-zone-glance': widget, 'data-glance-placement': placement, 'data-glance-tile': tile.key }}
      onmenu={menu}
    >
      {#snippet body()}<Tile data={tile.data} {onopen} />{/snippet}
    </TabKey>
  {/each}
{:else}
  <TabKey
    id={placement}
    shape="tile"
    variant="glance"
    classes="dz-glance--icon"
    face={keyFace({
      ariaLabel: t('drawer_zone.glance_open', { title: t(manifest.titleKey) }),
      tip: glance ? t(manifest.titleKey) : t('widgets.unavailable.glance', { title: t(manifest.titleKey) }),
    })}
    iconPx={14}
    quiet
    state={null}
    active={false}
    tabbable={null}
    style={`width: ${GLANCE_TILE_WIDTH_PX}px; height: ${GLANCE_TILE_HEIGHT_PX}px; color: var(--${manifest.iconTone});`}
    attrs={{ 'data-zone-glance': widget, 'data-glance-placement': placement, 'data-widget-unavailable': glance ? undefined : '' }}
    onpress={onopen}
    onmenu={menu}
  >
    {#snippet body()}<WidgetIcon name={manifest.icon} widget={manifest.id} size={14} /><span class="dz-glance-none">{t('drawer_zone.glance_none')}</span>{/snippet}
  </TabKey>
{/if}

<style>
  @layer components {
    .dz-glance-none {
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: 1;
    }
  }
</style>
