<script lang="ts" module>
  import { defineWidget } from '../../widgets/shell/define-widget.svelte';

  export const TERMINAL_GROUP_WIDGET = defineWidget({ id: 'core.terminal', scope: 'global', actions: [], state: {} });
</script>

<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../lib/cell';
  import TerminalCell from '../terminal/Cell.svelte';
  import PageTabBody from './PageTabBody.svelte';
  import { isPageTab, pageIdOfTab } from '../../engine/page-tabs';
  import { isNonSessionTab, isWidgetTab, widgetIdOfTab, widgetTabId } from '../../engine/widget-tabs';
  import WidgetTabBody from './WidgetTabBody.svelte';
  import { widgetTabBinding, widgetTabBodyKey } from './widget-tab-item';
  import { createWidgetTabSource } from './widget-tab-source.svelte';
  import PlacementMenuHost from '../../../lib/zone-shell/PlacementMenuHost.svelte';
  import { viewWidgetId } from '../../widgets/views';
  import DropOverlay from './DropOverlay.svelte';
  import TabStrip from '../../shell/TabStrip.svelte';
  import type { StripSlotProps } from '../../shell/frame-header.svelte';
  import WidgetShell from '../../widgets/shell/WidgetShell.svelte';
  import { useWidget } from '../../widgets/shell/define-widget.svelte';
  import { bindTerminalTheme } from '../terminal-live/theme';
  import { beginTabDrag } from '../../engine/tab-drag';
  import { dropIndexFor, tabDrag, zoneFor } from '../../engine/tab-drag-state.svelte';
  import CascadeMenu from '../../../lib/drawer-tabs/CascadeMenu.svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import { createTabController } from './tab-controller.svelte';
  import { widgetTabOptions } from './widget-tab-source.svelte';
  import ZoneShell from '../../../lib/zone-shell/ZoneShell.svelte';
  import ZoneToolbar from '../../../lib/zone-shell/ZoneToolbar.svelte';
  import { createZone } from '../../../lib/zone-shell/zone.svelte';
  import { linkZoneToFrame, seedFrameHeader } from '../../../lib/zone-shell/frame-link.svelte';
  import type { TabRef, ZoneMenuAnchor } from '../../../lib/zone-shell/zone-types';

  let props: CellProps = $props();

  let root = $state<HTMLElement | null>(null);

  let widgetMenu = $state<{ tab: string; anchor: HTMLElement; point: { x: number; y: number } | null } | null>(null);
  let menuSpot = $state<HTMLElement | null>(null);

  const widgetSource = createWidgetTabSource({
    remove: (tab) => ctl.close(tab),
    swap: (tab, view) => {
      const binding = widgetTabBinding(widgetIdOfTab(tab) ?? '');
      if (binding) ctl.swapWidgetTab(tab, widgetTabId(viewWidgetId(binding.widget, view)));
    },
  });

  function focusPane(tab: string): void {
    const pane = [...(root?.querySelectorAll<HTMLElement>('[data-tab-pane]') ?? [])]
      .find((el) => el.dataset.tabPane === tab);
    pane?.querySelector<HTMLElement>('textarea')?.focus({ preventScroll: true });
  }

  const ctl = createTabController(() => props.instance, focusPane);

  const widget = useWidget(TERMINAL_GROUP_WIDGET, () => props);
  const frameHeader = widget.frame;

  function onTabIcon(button: HTMLElement, frameMenu: (button: HTMLElement) => void): void {
    const tab = button.parentElement?.querySelector<HTMLElement>('[data-tab]')?.dataset.tab ?? '';
    if (isWidgetTab(tab) && zone.openMenu(tab, button)) return;
    frameMenu(button);
  }

  const zone = createZone({
    key: `grid:${untrack(() => props.instance)}`,
    tabs: (): TabRef[] => ctl.tabs.map((key) => ({ key, kind: isWidgetTab(key) ? 'widget' : isPageTab(key) ? 'page' : 'terminal' })),
    headerId: (tab) => (tab.kind === 'widget' ? widgetTabBodyKey(widgetIdOfTab(tab.key) ?? '') : null) ?? `grid:${untrack(() => props.instance)}#${tab.key}`,
    active: () => ctl.active,
    select: ctl.select,
    panel: () => 'open',
    strip: 'tabs',
    toolbar: 'strip',
    menuHost: 'tab',
    seedHeader: seedFrameHeader(frameHeader),
    openMenu: (tab, at: ZoneMenuAnchor) => {
      const anchor = at instanceof HTMLElement ? at : at.anchor;
      if (!anchor) return false;
      if (tab.kind === 'widget' && widgetTabBinding(widgetIdOfTab(tab.key) ?? '')) {
        widgetMenu = { tab: tab.key, anchor, point: at instanceof HTMLElement ? null : { x: at.x, y: at.y } };
        return true;
      }
      return ctl.openTabMenu(tab.key, anchor, at instanceof HTMLElement ? null : { x: at.x, y: at.y });
    },
  });
  linkZoneToFrame(zone, frameHeader, toolbar);

  $effect(() => {
    if (!frameHeader) return;
    frameHeader.strip = strip;
    return () => {
      if (frameHeader.strip === strip) frameHeader.strip = null;
    };
  });

  $effect(() => {
    if (!frameHeader || !isNonSessionTab(ctl.active)) return;
    const name = ctl.items.find((item) => item.id === ctl.active)?.name ?? '';
    frameHeader.title = name || null;
    return () => {
      frameHeader.title = null;
    };
  });

  $effect(() => {
    const frame = root?.closest<HTMLElement>('.oc-frame');
    if (!frame) return;
    return bindTerminalTheme({}, frame, { pinnedTheme: ctl.activePin });
  });
</script>

{#snippet widgetMenuHost(open: NonNullable<typeof widgetMenu>)}
  {@const binding = widgetTabBinding(widgetIdOfTab(open.tab) ?? '')}
  {#if binding}
    {#if open.point}
      <span class="oc-tg-spot" bind:this={menuSpot} style:left={`${open.point.x}px`} style:top={`${open.point.y}px`} aria-hidden="true"></span>
    {/if}
    <PlacementMenuHost
      host="tab"
      bodyHost="tab"
      manifest={binding.widget}
      view={binding.view}
      options={widgetTabOptions(open.tab)}
      placementKey={open.tab}
      source={widgetSource}
      pickView={(view) => widgetSource.setView(open.tab, view)}
      extras={{ tab: { close: () => ctl.close(open.tab) } }}
      anchor={open.point ? menuSpot : open.anchor}
      label={t('opscenter.frame.options', { title: t(binding.widget.titleKey) })}
      onClose={() => {
        open.anchor.focus();
        widgetMenu = null;
      }}
    />
  {/if}
{/snippet}

{#snippet toolbar()}
  <ZoneToolbar {zone} />
{/snippet}

{#snippet strip({ onIconClick, menuOpen, menuLabel }: StripSlotProps)}
  <TabStrip
    items={ctl.items}
    active={ctl.active}
    onSelect={ctl.select}
    onClose={ctl.close}
    onKill={(tab) => void ctl.kill(tab)}
    newOpen={ctl.newAnchor !== null}
    onNew={(button) => (ctl.newAnchor = ctl.newAnchor ? null : button)}
    onTabMenu={(id, anchor, point) => zone.openMenu(id, point ? { ...point, anchor } : anchor)}
    group={props.instance}
    dragging={tabDrag.tab}
    dropIndex={dropIndexFor(props.instance)}
    onDragStart={(button, event, tab) => void beginTabDrag(button, event, tab)}
    onIconClick={(button) => onTabIcon(button, onIconClick)}
    {menuOpen}
    {menuLabel}
  />
  {#if ctl.newAnchor}
    <CascadeMenu root={ctl.menu} anchor={ctl.newAnchor} label={t('opscenter.tabs.new')} onClose={() => (ctl.newAnchor = null)} />
  {/if}
  {#if ctl.tabMenuAnchor}
    <CascadeMenu root={ctl.tabMenuNodes} anchor={ctl.tabMenuAnchor} label={t('opscenter.tabs.menu_label')} onClose={ctl.closeTabMenu} />
  {/if}
{/snippet}

<WidgetShell {widget} bare>
<div class="oc-tg" bind:this={root}>
  <ZoneShell {zone} group>
    {#snippet tab(one)}
      {@const pageId = pageIdOfTab(one.key)}
      {#if pageId !== null}
        <PageTabBody browserId={pageId} />
      {:else if one.kind === 'widget'}
        <WidgetTabBody tab={one.key} source={widgetSource} />
      {:else}
        <TerminalCell
          width={props.width}
          height={props.height}
          meta={props.meta}
          instance={one.key}
          page={props.page}
        />
      {/if}
    {/snippet}
  </ZoneShell>
  <DropOverlay zone={zoneFor(props.instance)} />
  {#if widgetMenu}{@render widgetMenuHost(widgetMenu)}{/if}
</div>
</WidgetShell>

<style>
  @layer components {
    .oc-tg-spot {
      position: fixed;
      width: 0;
      height: 0;
      pointer-events: none;
    }

    .oc-tg {
      position: relative;
      flex: 1 1 auto;
      height: 100%;
      min-width: 0;
      min-height: 0;
    }
  }
</style>
