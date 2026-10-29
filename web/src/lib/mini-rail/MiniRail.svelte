<script lang="ts">
  import type { ListingPushGlobal } from '../listing-push/boot';
  import Glyph from '../Glyph.svelte';
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import { placeAt } from '../drawer-tabs/place-at';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import { railMenuNodes } from '../widget-menu/rail-menu';
  import { layoutEditor, toggleLayoutEditor } from '../../opscenter/layout-editor/editor.svelte';
  import { canOpen } from '../../opscenter/layout-editor/empty-space-menu.svelte';
  import type { SidebarRow } from '../sidebar-shell/legacy';
  import { arrange } from '../drawer/arrangement';
  import { rowHost } from '../sidebar-shell/row-host';
  import { t } from '../i18n/index.svelte';
  import { buildRailSections, type RailIconId } from './sections';
  import AlertBell from '../app-alerts/AlertBell.svelte';
  import { SESSION_LIST_WIDGET } from '../sidebar-widgets/widget-ids';
  import { RAIL_DESTINATIONS, type RailItem } from '../../opscenter/shell/rail-items';
  import { activeFlyout, showFlyout } from '../sidebar-widgets/flyout.svelte';
  import ZoneKeys from '../zone-shell/ZoneKeys.svelte';
  import TabKey, { keyFace } from '../zone-shell/TabKey.svelte';
  import { leftRailWidgets, leftRailZone } from '../zone-shell/left-rail-zone.svelte';
  import type { KeyFace, TabRef } from '../zone-shell/zone-types';
  import MiniRailFooter from './MiniRailFooter.svelte';
  import MiniRailUsage from './MiniRailUsage.svelte';

  const RAIL_CLASS = 'session-sidebar-railed';
  const POLL_MS = 5000;

  interface SidebarController {
    _rows?: SidebarRow[];
    open?: () => void;
    refreshNow?: () => Promise<void> | undefined;
  }

  interface RailGlobals {
    SessionSidebar?: SidebarController;
    SessionSidebarClicks?: { activateRow?: (ctrl: unknown, rowEl: Element) => Promise<void> };
  }

  const g = globalThis as unknown as RailGlobals;

  let railed = $state(false);
  let version = $state(0);
  let openSection = $state<RailIconId | null>(null);
  let sectionAnchor = $state<HTMLElement | null>(null);
  let rail = $state<HTMLElement | null>(null);
  const buttons: Partial<Record<string, HTMLElement | null>> = $state({});

  $effect(() => {
    const read = (): void => {
      railed = document.body.classList.contains(RAIL_CLASS);
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  });

  $effect(() => {
    if (!railed) return;
    const list = document.getElementById('session-sidebar-list');
    if (!list) return;
    const observer = new MutationObserver(() => {
      version += 1;
    });
    observer.observe(list, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-listing-ok'] });
    void refresh();
    const tick = (): void => {
      if (!document.hidden) void refresh();
    };
    const push = (window as unknown as { ListingPush?: ListingPushGlobal }).ListingPush;
    const stop = push && typeof push.pushOrPoll === 'function'
      ? push.pushOrPoll(tick, POLL_MS, ['list', 'attachable', 'records', 'companions'])
      : ((): (() => void) => {
          const handle = setInterval(tick, POLL_MS);
          return () => clearInterval(handle);
        })();
    return () => {
      observer.disconnect();
      stop();
    };
  });

  $effect(() => {
    if (!railed) {
      openSection = null;
    } else if (openSection && !sections.some((s) => s.id === openSection)) {
      openSection = null;
    }
  });

  async function refresh(): Promise<void> {
    await g.SessionSidebar?.refreshNow?.();
    version += 1;
  }

  const sections = $derived.by(() => {
    void version;
    if (!railed) return [];
    const raw = g.SessionSidebar?._rows ?? [];
    const rows = arrange(raw).rows;
    return buildRailSections({
      rows,
      host: rowHost(),
      open: openRow,
      asleepLabel: t('session.asleep.label'),
    });
  });

  const current = $derived(sections.find((s) => s.id === openSection) ?? null);

  function openRow(name: string, attrs: Record<string, string | undefined>): void {
    const ctl = g.SessionSidebar;
    const activate = g.SessionSidebarClicks?.activateRow;
    openSection = null;
    if (!ctl || !activate) return;
    const escaped = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(name) : name;
    let row: Element | null = document.querySelector(`#session-sidebar-list .session-sidebar-row[data-name="${escaped}"]`);
    if (!row) {
      row = document.createElement('div');
      for (const [key, value] of Object.entries(attrs)) {
        if (key.startsWith('data-') && value !== undefined) row.setAttribute(key, value);
      }
    }
    void activate(ctl, row);
  }

  function toggleSection(id: RailIconId): void {
    openSection = openSection === id ? null : id;
    sectionAnchor = buttons[id] ?? null;
    if (openSection) void refresh();
  }

  const settingsItem = RAIL_DESTINATIONS.find((i) => i.id === 'settings');

  function runItem(item: RailItem): void {
    openSection = null;
    item.run?.();
  }

  const zone = leftRailZone();
  const railKeys = $derived(leftRailWidgets());
  const flyoutNow = $derived(activeFlyout() ?? SESSION_LIST_WIDGET);
  const widgetOf = $derived(new Map(railKeys.map((widget) => [widget.id, widget])));

  function face(tab: TabRef): KeyFace {
    const widget = widgetOf.get(tab.key)!;
    const badge = widget.badge?.() ?? null;
    const name = t(widget.titleKey);
    const spoken = badge === null ? name : t('sidebar.rail.with_count', { name, count: badge });
    return { title: name, ariaLabel: spoken, tip: spoken, label: name, icon: widget.icon, count: badge, chip: false, letter: '', tone: 'oc-text-secondary' };
  }

  function pressKey(key: string): void {
    const widget = widgetOf.get(key);
    openSection = null;
    if (!widget) return;
    if (widget.action) {
      widget.action();
      return;
    }
    showFlyout(widget.id);
    g.SessionSidebar?.open?.();
  }

  let menuAt = $state<{ x: number; y: number } | null>(null);
  let menuMarker = $state<HTMLElement | null>(null);

  function onRailContextMenu(event: MouseEvent): void {
    if (event.defaultPrevented || (event.target instanceof Element && event.target.closest('.acm-menu'))) return;
    event.preventDefault();
    menuAt = { x: event.clientX, y: event.clientY };
  }

  function menuNodes(): MenuNode[] {
    return railMenuNodes({
      editing: layoutEditor.active,
      openDrawer: () => g.SessionSidebar?.open?.(),
      toggleEdit: canOpen() ? () => void toggleLayoutEditor() : null,
      onClose: () => (menuAt = null),
    });
  }
</script>

<nav class="mr" aria-label={t('drawer.rail.label')} data-tooltip-side="right" bind:this={rail} oncontextmenu={onRailContextMenu}>
  <TabKey id="claw" variant="mini" classes="mr-claw" face={keyFace({ ariaLabel: t('drawer.rail.open'), tip: t('drawer.rail.open') })} iconPx={16}
          quiet state="expanded" active={false} tabbable attrs={{ 'data-rail': 'claw', 'aria-controls': 'session-sidebar-panel' }}
          onpress={() => g.SessionSidebar?.open?.()}>
    {#snippet body()}<img src="/static/img/carnivore/carnivore-mark.png" srcset="/static/img/carnivore/carnivore-mark@2x.png 2x" alt="" />{/snippet}
  </TabKey>
  
  
  <AlertBell place="rail" />

  <div class="mr-tabs" role="group" aria-label={t('sidebar.rail.label')}>
    <ZoneKeys zones={[zone]} axis="y" ratio={0} labelAt="none" iconPx={14} compact={false} editing={false} openKeys={new Set([flyoutNow])} {face}
      mark={null} empty={null} flow toggle home={flyoutNow} onpress={(_zone, key) => pressKey(key)} onedit={() => {}} ondragstart={() => {}} />
  </div>

  <div class="mr-items" role="group" aria-label={t('drawer.rail.items')}>
    {#each sections as section (section.id)}
      <TabKey id={section.id} variant="mini" face={keyFace({ ariaLabel: t(section.labelKey), tip: t(section.labelKey) })} iconPx={16}
              quiet state="expanded" active={openSection === section.id} tabbable
              attrs={{ 'data-rail-section': section.id, 'aria-haspopup': 'menu' }} bind:element={buttons[section.id]}
              onpress={() => toggleSection(section.id)}>
        {#snippet body()}<Glyph name={section.glyph} size={16} />{/snippet}
      </TabKey>
    {/each}
  </div>

  
  {#if settingsItem}
    <div class="mr-settings">
      <TabKey id="settings" variant="mini"
              face={keyFace({ ariaLabel: t(settingsItem.labelKey), tip: t(settingsItem.labelKey), icon: settingsItem.icon })} iconPx={16}
              quiet state={null} active={false} tabbable attrs={{ 'data-rail-settings': '' }} onpress={() => runItem(settingsItem)} />
    </div>
  {/if}

  <MiniRailFooter {railed} />

  <MiniRailUsage />

  {#if current}
    <CascadeMenu root={current.nodes} anchor={sectionAnchor} nestedIn={rail}
                 label={t(current.labelKey)} onClose={() => (openSection = null)} />
  {/if}

  {#if menuAt}
    <span class="mr-menu-anchor" bind:this={menuMarker} use:placeAt={menuAt} aria-hidden="true"></span>
    {#if menuMarker}
      {#key `${menuAt.x},${menuAt.y}`}
        <CascadeMenu root={menuNodes()} anchor={menuMarker} label={t('drawer.rail.menu.label')} onClose={() => (menuAt = null)} />
      {/key}
    {/if}
  {/if}
</nav>

<style>
  @layer components {
    .mr-menu-anchor { position: fixed; width: 0; height: 0; pointer-events: none; }
    .mr {
      position: fixed;
      top: var(--desktop-inset-top, 0px);
      left: 0;
      bottom: 0;
      z-index: 1100;
      width: var(--sidebar-rail-w, 48px);
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: var(--oc-space-2) 0;
      background: var(--oc-ground-chrome);
      border-right: var(--oc-border) solid var(--oc-line-chrome);
      font-family: var(--font-mono);
      overflow: hidden;
    }

    .mr-tabs,
    .mr-items {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      width: 100%;
    }

    .mr-tabs {
      flex: 0 0 auto;
    }

    .mr-tabs {
      padding-bottom: 6px;
      box-shadow: 0 1px 0 var(--oc-line-panel);
    }

    .mr-items {
      flex: 1 1 auto;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
    }

    .mr {
      --oc-ibtn-size: 32px;
    }

    :global(.mr-claw) img {
      width: 26px;
      height: 26px;
      opacity: 0.85;
    }

    :global(.mr-claw:hover) img,
    :global(.mr-claw:focus-visible) img {
      opacity: 1;
    }

    .mr-settings {
      flex: 0 0 auto;
      display: flex;
      justify-content: center;
      width: 100%;
    }

  }
</style>
