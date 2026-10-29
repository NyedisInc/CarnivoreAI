<script lang="ts">
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import { t } from '../i18n/index.svelte';
  import { resolvePlacement } from '../../opscenter/widgets/placement-resolve';
  import { HEADER_OPTION, placementHeaderShown } from '../../opscenter/shell/widget-head';
  import { toggleLayoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import { canOpen } from '../../opscenter/layout-editor/empty-space-menu.svelte';
  import { terminalLayout } from '../../opscenter/engine/layout.svelte';
  import { zoneItemKey } from '../drawer-zone/zone-model';
  import { alertCountSource } from '../session-rail/alert-counts';
  import { railStores, otherEdge, placeInRail, railEnd } from '../session-rail/rail-store.svelte';
  import type { RailEdge } from '../session-rail/rail-model';
  import type { ArrangeEntry } from './model';
  import PlacementMenuHost from '../zone-shell/PlacementMenuHost.svelte';
  import { railSlideout } from '../session-rail/slideout.svelte';
  import { panelPins } from '../widget-bars/panel-pins.svelte';
  import { barLead } from '../widget-bars/bar-lead.svelte';

  let { edge, itemKey, anchor, onClose }: { edge: RailEdge; itemKey: string; anchor: HTMLElement | null; onClose: () => void } = $props();

  const store = $derived(railStores[edge]);
  const item = $derived(store.items.find((one) => zoneItemKey(one) === itemKey));
  const resolved = $derived(item ? resolvePlacement({ widget: item.widget, view: item.view }) : null);
  const manifest = $derived(resolved?.manifest);
  const cell = $derived(resolved?.cell);
  const title = $derived(manifest ? t(manifest.titleKey) : '');

  const badge = $derived.by((): MenuNode[] => {
    const menu = cell ? alertCountSource(cell.id)?.menu : undefined;
    return menu ? [{ id: 'count-in-badge', label: t(menu.headingKey), children: menu.nodes().map((node) => ({ ...node, keepOpen: true })) }] : [];
  });

  const sectionOf = $derived(store.sections.find((section) => section.some((one) => zoneItemKey(one) === itemKey)) ?? []);
  const at = $derived(sectionOf.findIndex((one) => zoneItemKey(one) === itemKey));
  const other = $derived(otherEdge(edge));

  const arrange = $derived<ArrangeEntry[]>([
    { item: 'moveUp', blocked: at <= 0 ? t('widgets.menu.already_first') : undefined, run: () => store.step(itemKey, -1) },
    { item: 'moveDown', blocked: at < 0 || at >= sectionOf.length - 1 ? t('widgets.menu.already_last') : undefined, run: () => store.step(itemKey, 1) },
    {
      item: 'moveToBar',
      label: t(other === 'side' ? 'widgets.menu.move_to_side' : 'widgets.menu.move_to_bottom'),
      run: () => {
        if (item) placeInRail(other, item.widget, railEnd(other), item.target, item);
      },
    },
  ]);

  const headerShown = $derived(item && manifest ? placementHeaderShown('rail', item.options, manifest.id) : false);

  function openPanel(): void {
    const wasOut = railSlideout.shown(edge).length > 0;
    railSlideout.open(itemKey);
    if (!wasOut && railSlideout.shown(edge).length > 0) barLead.take(edge);
  }
</script>

{#if manifest && item}
  <PlacementMenuHost
    host="bar-key"
    bodyHost="rail"
    {manifest}
    view={item.view ?? null}
    target={item.target ?? null}
    instance={item.instance ?? null}
    options={item.options}
    placementKey={itemKey}
    source={store}
    lead={badge.length ? [badge] : []}
    extras={{
      header: { shown: headerShown, toggle: () => store.setOption(itemKey, HEADER_OPTION, !headerShown) },
      arrange,
      editLayout: canOpen() ? () => void toggleLayoutEditor() : null,
      close: {
        instance: manifest.instancing !== 'singleton' || !!item.instance,
        run: () => {
          if (store.remove(itemKey)) terminalLayout.announce(t('session_rail.announce.removed', { title }));
        },
      },
    }}
    openHost={openPanel}
    pinRowId={panelPins.pinnedRow(edge, itemKey)}
    {edge}
    {anchor}
    label={t('widget.view.menu', { title })}
    {onClose}
  />
{/if}
