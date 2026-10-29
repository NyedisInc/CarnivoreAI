<script lang="ts">
  /*  hidden  */
  import Icon from '../../opscenter/ui/Icon.svelte';
  import IconButton from '../base/IconButton.svelte';
  import ComponentsPopover from '../../opscenter/engine/ComponentsPopover.svelte';
  import { navAnchors } from '../../opscenter/engine/navAnchors.svelte';
  import { homeLayout } from '../../opscenter/engine/layout.svelte';
  import { viewport } from '../../opscenter/engine/viewport.svelte';
  import { RAIL_HELP_LINKS, WARROOM_ROW, railItemVisible, type RailItem } from '../../opscenter/shell/rail-items';
  import { closeDrawerAfterSwitch, handleMenuHotkey } from './menu-hotkeys';
  import { drawerSurface, storeFor } from './drawer-surface.svelte';
  import { t } from '../i18n/index.svelte';
  import { menuPageState } from '../menu-page/menu-page-shell.svelte';
  import { menuPage } from '../menu-page/menu-pages';
  import { menuRowPopout } from '../../opscenter/shell/open-targets';
  import { dashboardLayout } from '../dashboards/board-layout';
  import MenuPreview from './MenuPreview.svelte';
  import { onMount } from 'svelte';
  import { saveMenuOrder, startMenuOrder } from './menu-order.svelte';
  import BarPin from '../widget-bars/BarPin.svelte';
  import { menuDestinations, menuLeadItems, menuSettings } from './menu-rows';
  import { onMenuMoveKey, onMenuPointerDown, type MenuDragHost } from './menu-drag';
  import {
    hideMenuPreview,
    menuDashboardRows,
    menuPreview,
    openMenuDashboard,
    editMenuDashboards,
    menuDashboardsFold,
    popOutMenuDashboard,
    showMenuPreview,
    toggleMenuDashboards,
  } from './menu-dashboards.svelte';

  const store = $derived(storeFor(drawerSurface.page) ?? homeLayout);
  const hiddenCount = $derived(store.hiddenCells().length);
  const activeRow = $derived(menuPageState.open ? (menuPage(menuPageState.open)?.railItem ?? null) : null);

  function activate(item: RailItem): void {
    item.run?.();
    closeDrawerAfterSwitch();
  }

  const rows = $derived(menuDestinations());
  const leadRows = $derived(menuLeadItems());
  const settingsRow = menuSettings();
  const dragHost: MenuDragHost = { ids: () => rows.map((r) => r.id), commit: saveMenuOrder };
  onMount(startMenuOrder);

  function onMenuKeydown(event: KeyboardEvent): void {
    if (!onMenuMoveKey(event, dragHost)) handleMenuHotkey(event);
  }

  const dashboardRows = $derived(menuDashboardRows());
  const previewRow = $derived(dashboardRows.find((row) => row.id === menuPreview.id) ?? null);

  function lineOf(event: Event): HTMLElement | null {
    return (event.currentTarget as HTMLElement).closest<HTMLElement>('li');
  }

  let componentsOpen = $state(false);
  let componentsButton = $state<HTMLElement | null>(null);

  $effect(() => {
    if (!componentsButton) return;
    const mine = componentsButton;
    navAnchors.components = mine;
    return () => {
      if (navAnchors.components === mine) navAnchors.components = null;
    };
  });
</script>


<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<nav class="oc-sidebar" aria-label={t('opscenter.nav.primary')} onkeydown={onMenuKeydown} onpointerdown={(e) => onMenuPointerDown(e, dragHost)}>
  <ul class="oc-nav oc-nav-lead">
    {#each leadRows as item (item.id)}
      {@const count = item.badge?.() ?? null}
      <li class="oc-nav-line" data-menu-lead={item.id}>
        <button type="button" class="oc-nav-item" aria-pressed={item.pressed?.() ?? false}
                data-rail-item={item.id} onclick={() => item.run?.()}>
          <span class="oc-nav-icon"><Icon name={item.icon} size={17} /></span>
          <span class="oc-nav-label">{t(item.labelKey)}</span>
          {#if count}<span class="oc-nav-badge">{count}</span>{/if}
        </button>
      </li>
    {/each}
  </ul>
  <ul class="oc-nav">
    {#each rows as item (item.id)}
      {@const popOut = menuRowPopout(item.id)}
      <li class="oc-nav-line" data-menu-row={item.id}>
        <button type="button" class="oc-nav-item" class:oc-nav-item--active={activeRow === item.id}
                aria-current={activeRow === item.id ? 'page' : undefined}
                data-rail-item={item.id} onclick={() => activate(item)}>
          <span class="oc-nav-icon"><Icon name={item.icon} size={17} /></span>
          <span class="oc-nav-label">{t(item.labelKey)}</span>
          {#if item.id !== 'dashboards'}<span class="oc-nav-hint">{item.hint}</span>{/if}
        </button>
        {#if item.id === 'dashboards'}
          <IconButton label={t('opscenter.nav.dashboards_list')} variant="quiet" icon="chevron-down" iconSize={14}
                      data-menu-dashboards-caret aria-expanded={menuDashboardsFold.open} onclick={toggleMenuDashboards} />
        {:else if popOut}
          <IconButton label={t('opscenter.nav.pop_out', { name: t(item.labelKey) })} variant="quiet" icon="external"
                      data-menu-popout={item.id} onclick={popOut} />
        {/if}
      </li>
      {#if item.id === 'dashboards' && menuDashboardsFold.open}
        
        {#if railItemVisible(WARROOM_ROW)}
          {@const warPopOut = menuRowPopout(WARROOM_ROW.id)}
          <li class="oc-nav-line oc-nav-sub" data-menu-row={WARROOM_ROW.id}>
            <button type="button" class="oc-nav-item" class:oc-nav-item--active={activeRow === WARROOM_ROW.id}
                    aria-current={activeRow === WARROOM_ROW.id ? 'page' : undefined}
                    data-rail-item={WARROOM_ROW.id} onclick={() => activate(WARROOM_ROW)}>
              <span class="oc-nav-icon"><Icon name={WARROOM_ROW.icon} size={13} /></span>
              <span class="oc-nav-label oc-nav-label--name">{t(WARROOM_ROW.labelKey)}</span>
            </button>
            {#if warPopOut}
              <IconButton label={t('opscenter.nav.pop_out', { name: t(WARROOM_ROW.labelKey) })} variant="quiet" icon="external"
                          data-menu-popout={WARROOM_ROW.id} onclick={warPopOut} />
            {/if}
          </li>
        {/if}
        {#each dashboardRows as row (row.id)}
          <li class="oc-nav-line oc-nav-sub">
            <button type="button" class="oc-nav-item" class:oc-nav-item--active={row.viewing}
                    aria-current={row.viewing ? 'page' : undefined} data-menu-dashboard={row.id}
                    aria-label={t(row.home ? 'opscenter.nav.dashboard_home' : 'opscenter.nav.dashboard_open', { name: row.name })}
                    onpointerenter={(event) => showMenuPreview(row.id, lineOf(event))}
                    onpointerleave={() => hideMenuPreview(row.id)}
                    onfocus={(event) => showMenuPreview(row.id, lineOf(event))}
                    onblur={() => hideMenuPreview(row.id)}
                    onclick={() => openMenuDashboard(row.id)}>
              <span class="oc-nav-icon"><Icon name="layout" size={13} /></span>
              <span class="oc-nav-label oc-nav-label--name">{row.name}</span>
              {#if row.home}
                <span class="oc-nav-star" role="img" aria-label={t('opscenter.nav.dashboard_default')}
                      title={t('opscenter.nav.dashboard_default')}><Icon name="star" size={11} fill="solid" /></span>
              {/if}
            </button>
            <IconButton label={t('opscenter.nav.pop_out', { name: row.name })} variant="quiet" icon="external"
                        data-menu-popout={`dashboard:${row.id}`} onclick={() => popOutMenuDashboard(row.id)} />
          </li>
        {/each}
        <li class="oc-nav-line oc-nav-sub">
          <button type="button" class="oc-nav-item oc-nav-edit" data-menu-dashboards-edit onclick={editMenuDashboards}>
            <span class="oc-nav-label oc-nav-label--name">{t('opscenter.nav.dashboards_edit')}</span>
          </button>
        </li>
      {/if}
      {#if item.id === 'widgets' && !viewport.wide}
      <li class="oc-nav-components">
        <button
          type="button"
          class="oc-nav-item"
          data-rail-item="components"
          bind:this={componentsButton}
          aria-haspopup="dialog"
          aria-expanded={componentsOpen}
          aria-label={hiddenCount
            ? t('opscenter.nav.components_hidden_label', { count: hiddenCount })
            : t('opscenter.nav.components_label')}
          onclick={() => (componentsOpen = !componentsOpen)}
        >
          <span class="oc-nav-icon"><Icon name="components" size={17} /></span>
          <span class="oc-nav-label">{t('opscenter.nav.components')}</span>
          {#if hiddenCount > 0}
            <span class="oc-nav-badge">{hiddenCount}</span>
          {/if}
        </button>
        {#if componentsOpen}
          <ComponentsPopover anchor={componentsButton} {store} onClose={() => (componentsOpen = false)} />
        {/if}
      </li>
      {/if}
    {/each}
  </ul>

  {#if menuPreview.id && previewRow}
    <MenuPreview anchor={menuPreview.anchor} layout={dashboardLayout(menuPreview.id)} name={previewRow.name}
                 home={previewRow.home} />
  {/if}

  <h2 class="oc-sidebar-head">{t('opscenter.nav.help')}</h2>
  <ul class="oc-nav oc-nav-quick">
    {#each RAIL_HELP_LINKS as item (item.id)}
      <li>
        <button type="button" class="oc-nav-item" class:oc-nav-item--active={activeRow === item.id}
                aria-current={activeRow === item.id ? 'page' : undefined}
                data-rail-item={item.id} onclick={() => activate(item)}>
          <span class="oc-nav-icon"><Icon name={item.icon} size={15} /></span>
          <span class="oc-nav-label">{t(item.labelKey)}</span>
          <span class="oc-nav-hint">{item.hint}</span>
        </button>
      </li>
    {/each}
  </ul>
  {#if settingsRow}
    <ul class="oc-nav oc-nav-settings">
      <li>
        <button type="button" class="oc-nav-item" class:oc-nav-item--active={activeRow === settingsRow.id}
                aria-current={activeRow === settingsRow.id ? 'page' : undefined}
                data-rail-item={settingsRow.id} onclick={() => activate(settingsRow)}>
          <span class="oc-nav-icon"><Icon name={settingsRow.icon} size={17} /></span>
          <span class="oc-nav-label">{t(settingsRow.labelKey)}</span>
          <span class="oc-nav-hint">{settingsRow.hint}</span>
        </button>
        
        <span class="oc-nav-pin"><BarPin edge="rail" /></span>
      </li>
    </ul>
  {/if}
</nav>

<style>
  @layer components {
    .oc-sidebar {
      display: flex;
      flex-direction: column;
      flex: 1 1 auto;
      padding: 10px var(--oc-space-2) var(--oc-space-3);
      overflow-y: auto;
      overflow-x: hidden;
    }

    .oc-nav {
      list-style: none;
      margin: 0;
      padding: 0;
    }

    .oc-nav-lead {
      margin-bottom: calc(var(--oc-space-0-5) / 2);
    }

    .oc-nav-item[aria-pressed='true'] {
      background: var(--oc-ground-hover);
      border-color: var(--oc-line-rule);
      color: var(--oc-text-primary);
    }

    .oc-nav-settings {
      margin-top: auto;
      padding-top: var(--oc-space-3);
    }

    .oc-nav-settings li {
      position: relative;
    }

    /* padding */
    .oc-nav-settings .oc-nav-item {
      padding-right: calc(var(--oc-space-5) + var(--oc-space-4));
    }

    .oc-nav-pin {
      position: absolute;
      top: 50%;
      right: 4px;
      transform: translateY(-50%);
      display: flex;
    }

    .oc-nav li + li {
      margin-top: 1px;
    }

    .oc-nav-item {
      display: flex;
      align-items: center;
      /* padding */
      gap: 20px;
      width: 100%;
      height: 33px;
      padding: 0 10px 0 13px;
      background: none;
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius);
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-nav);
      text-align: left;
      cursor: pointer;
    }

    .oc-nav-item:hover {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }

    .oc-nav-item--active {
      background: var(--oc-ground-hover);
      border-color: var(--oc-line-rule);
      color: var(--oc-text-primary);
    }

    .oc-nav-item--active .oc-nav-icon {
      color: var(--oc-orange);
    }

    .oc-nav-icon {
      display: inline-flex;
      flex: 0 0 auto;
      color: var(--oc-text-muted);
    }

    .oc-nav-label {
      text-transform: capitalize;
      flex: 1 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .oc-nav-hint {
      flex: 0 0 auto;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .oc-nav-components {
      position: relative;
    }

    .oc-nav-line {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
    }

    .oc-nav-line:global([data-menu-lifted]),
    .oc-nav-line:global([data-menu-drop]) {
      position: relative;
    }

    .oc-nav-line:global([data-menu-lifted])::after,
    .oc-nav-line:global([data-menu-drop])::after {
      content: '';
      position: absolute;
      inset: 0;
      pointer-events: none;
    }

    .oc-nav-line:global([data-menu-lifted])::after {
      background: var(--oc-ground-hover);
      box-shadow: inset 0 0 0 1px var(--oc-line-panel);
      opacity: 0.7;
    }

    .oc-nav-line:global([data-menu-drop='before'])::after {
      border-top: 2px solid var(--oc-orange);
    }

    .oc-nav-line:global([data-menu-drop='after'])::after {
      border-bottom: 2px solid var(--oc-orange);
    }

    .oc-nav-line > .oc-nav-item {
      flex: 1 1 auto;
      min-width: 0;
    }

    .oc-nav-line :global([data-menu-popout]) {
      --oc-ibtn-size: 26px;
      flex: 0 0 auto;
    }

    .oc-nav-sub .oc-nav-item {
      height: 27px;
      padding-left: calc(var(--oc-space-5) + var(--oc-space-3));
      gap: var(--oc-space-2);
      font-size: var(--oc-fs-label);
    }

    .oc-nav-sub .oc-nav-edit {
      padding-left: calc(var(--oc-space-5) + var(--oc-space-3) + 13px + var(--oc-space-2));
    }

    .oc-nav-label--name {
      text-transform: none;
    }

    .oc-nav-line :global([data-menu-dashboards-caret]) {
      --oc-ibtn-size: 26px;
      flex: 0 0 auto;
    }

    .oc-nav-line :global([data-menu-dashboards-caret] svg) {
      transition: transform 120ms;
    }

    .oc-nav-line :global([data-menu-dashboards-caret][aria-expanded='true'] svg) {
      transform: rotate(180deg);
    }

    .oc-nav-star {
      display: inline-flex;
      flex: 0 0 auto;
      color: var(--oc-green);
    }

    .oc-nav-badge {
      flex: 0 0 auto;
      min-width: 18px;
      padding: 1px 5px;
      border-radius: 9px;
      background: var(--oc-orange-tint);
      color: var(--oc-orange);
      font-size: var(--oc-fs-micro);
      text-align: center;
    }

    .oc-sidebar-head {
      text-transform: uppercase;
      margin: 22px 0 var(--oc-space-2);
      padding: 0 13px;
      font-size: var(--oc-fs-label);
      font-weight: 400;
      letter-spacing: var(--oc-tracking-label);
      color: var(--oc-text-dim);
    }

    .oc-nav-quick .oc-nav-item {
      height: 29px;
    }

    @media (max-width: 1023px) {
      .oc-nav-item,
      .oc-nav-quick .oc-nav-item {
        height: var(--oc-tap);
      }
    }
  }
</style>
