<script lang="ts">
  /**
   * THE SLIDE-OUT HOST of the rail layout (issue #1774), mounted into
   * `#session-sidebar-flyout`, which covers the session list region (search and list) and nothing else: the stats strip
   * above it and the widget area and bar below it stay in view.
   *
   * Description: draws the open slide-out (`flyout.svelte.ts`) as ONE element, its title row and its body together, so
   *   both slide at the same speed (about 180ms in, 140ms out, none under reduced motion or with the app's motion off).
   *   The width is ONE variable, `--sidebar-flyout-w` (`sidebar-rail.css`). The title row is the title-row ground
   *   washed with the widget's MANDATORY tint at 16% (color-mix), a large title, the icon in the solid tint and the X;
   *   no borders anywhere. A widget's own toolbar (a dynamic tab's title actions) gets a row of its own under the title
   *   row, never a place in it. The body is the widget's existing component, or a dynamic tab's own body (swarm is the
   *   Task Manager tab's), drawn in the left rail ZONE's pane (`zone-shell/left-rail-zone.svelte.ts`), so it has its own frame
   *   header and the tab-pane context with the visibility rune. A swap between slide-outs replaces the contents in place with no slide; a close
   *   keeps the contents until the slide has finished, then unmounts them.
   *   Escape closes it while focus is inside it or on the rail (inner popups first); from anywhere else but a terminal, an Escape
   *   closes it only while the rail is UNPINNED, through the shared strip layer (`widget-bars/strip-escape.svelte.ts`, the team,
   *   an earlier date). A transient slide-out (the menu) closes on a press outside the slide-out and the rail.
   */
  import type { Component } from 'svelte';
  import IconButton from '../base/IconButton.svelte';
  import CornerMenu from '../../opscenter/shell/CornerMenu.svelte';
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import type { MenuSlot } from '../../opscenter/shell/widget-head';
  import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';
  import { declaredGroups } from '../widget-menu/declared-nodes';
  import { railNodesFor } from './rail-menu.svelte';
  import { t } from '../i18n/index.svelte';
  import './flyout-title.css';
  import { motionReduced } from '../motion/motion';
  import { tabRegistry } from '../dynamic-tabs/registry';
  import {
    activeFlyout,
    closeFlyout,
    closeFlyoutIfGone,
    flyoutWidget,
    handleFlyoutEscape,
    handleOutsidePress,
  } from './flyout.svelte';
  import ZonePane from '../zone-shell/ZonePane.svelte';
  import { leftRailZone, setDrawnFlyout } from '../zone-shell/left-rail-zone.svelte';
  import type { TabRef } from '../zone-shell/zone-types';
  import { widgetBars } from '../widget-bars/bar-settings.svelte';
  import { RAIL_CONTAINER_ID } from './rail-dom';
  import { hideMainView, showMainView } from './main-view';
  import { MENU_FLYOUT } from './widget-ids';
  import { isMountedPart, isTabBodyPart, type SidebarWidget } from './types';

  const OPEN_MS = 180;
  const CLOSE_MS = 140;

  const active = $derived(activeFlyout());
  let shown = $state<string | null>(null);
  let host = $state<HTMLElement | null>(null);

  $effect(() => {
    if (active !== null) {
      shown = active;
      return;
    }
    if (motionReduced()) {
      shown = null;
      return;
    }
    const timer = setTimeout(() => (shown = null), CLOSE_MS + 20);
    return () => clearTimeout(timer);
  });

  $effect(() => {
    if (active === null) return;
    const onPress = (event: Event): void => {
      handleOutsidePress(event, [host?.parentElement ?? null, document.getElementById(RAIL_CONTAINER_ID)]);
    };
    document.addEventListener('pointerdown', onPress, true);
    return () => document.removeEventListener('pointerdown', onPress, true);
  });

  const widget = $derived<SidebarWidget | null>(flyoutWidget(shown));
  $effect(() => {
    const region = host?.closest<HTMLElement>('.sbr-region');
    if (!region) return;
    if (shown !== MENU_FLYOUT) {
      region.style.removeProperty('--sbr-lift');
      region.style.removeProperty('--sbr-drop');
      delete region.dataset.sbrMenu;
      return;
    }
    const below = ['session-sidebar-area-bar', 'session-sidebar-ledger']
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);
    const measure = (): void => {
      region.style.setProperty('--sbr-lift', `${document.getElementById('session-sidebar-stats')?.offsetHeight ?? 0}px`);
      const bottom = Math.max(...below.filter((el) => el.offsetParent !== null).map((el) => el.getBoundingClientRect().bottom), 0);
      region.style.setProperty('--sbr-drop', `${Math.max(0, bottom - region.getBoundingClientRect().bottom)}px`);
    };
    region.dataset.sbrMenu = '';
    measure();
    const watch = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    for (const el of below) watch?.observe(el);
    return () => {
      watch?.disconnect();
      region.style.removeProperty('--sbr-lift');
      region.style.removeProperty('--sbr-drop');
      delete region.dataset.sbrMenu;
    };
  });
  $effect(() => {
    const part = active === null ? undefined : flyoutWidget(active)?.parts.body;
    const view = part && isTabBodyPart(part) ? tabRegistry.get(part.tab)?.mainView : undefined;
    if (!view) return;
    showMainView(view);
    return () => hideMainView();
  });
  const titleRow = $derived(!(widget?.id === MENU_FLYOUT && widgetBars.rail.mode === 'autohide'));

  const body = $derived.by<{ component: Component | null; actions: Component<{ popout?: boolean }> | null }>(() => {
    const part = widget?.parts.body;
    if (!part) return { component: null, actions: null };
    if (isMountedPart(part)) return { component: part.component as Component, actions: null };
    if (!isTabBodyPart(part)) return { component: null, actions: null };
    const def = tabRegistry.get(part.tab);
    if (!def || !('component' in def.body)) return { component: null, actions: null };
    return { component: def.body.component, actions: def.body.titleActions ?? null };
  });

  $effect(() => {
    closeFlyoutIfGone();
  });

  const zone = leftRailZone();
  $effect(() => {
    setDrawnFlyout(shown);
    return () => setDrawnFlyout(null);
  });
  const drawnTab = $derived<TabRef | null>(shown === null ? null : { key: shown, kind: 'panel' });

  function menuNodes(onClose: () => void = () => {}): MenuNode[] {
    if (!widget || !drawnTab) return [];
    return railNodesFor(widget.id, onClose, declaredGroups(declaredActionsFor(zone.headerIdOf(drawnTab))));
  }

  function onKeydown(event: KeyboardEvent): void {
    handleFlyoutEscape(event, host?.parentElement ?? null);
  }

  function close(): void {
    const was = active;
    closeFlyout();
    if (was) document.querySelector<HTMLElement>(`[data-rail-widget="${was}"]`)?.focus();
  }
</script>

{#snippet cornerMenu(slot: MenuSlot)}
  <CascadeMenu root={menuNodes(slot.close)} anchor={slot.anchor} label={t('opscenter.frame.options', { title: t(widget!.titleKey) })} onClose={slot.close} />
{/snippet}

{#snippet pane()}
  {#if body.component}<body.component />{/if}
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<section
  class="sbr-flyout"
  class:sbr-flyout--open={active !== null}
  data-flyout={widget?.id}
  style:--sbr-tint={widget?.tint ? `var(${widget.tint})` : undefined}
  style:--sbr-open-ms={`${OPEN_MS}ms`}
  style:--sbr-close-ms={`${CLOSE_MS}ms`}
  aria-label={widget ? t(widget.titleKey) : undefined}
  inert={active === null}
  bind:this={host}
  onkeydown={onKeydown}
>
  {#if widget}
    {#if titleRow}
    <header class="sbr-flyout__title">
      <span class="sbr-flyout__icon">
        <CornerMenu meta={{ id: widget.id, icon: widget.icon }} title={t(widget.titleKey)} editing={false} place="row" menu={menuNodes().length > 0 ? cornerMenu : null} />
      </span>
      <h2 class="sbr-flyout__name">{t(widget.titleKey)}</h2>
      <IconButton label={t('sidebar.flyout.close', { name: t(widget.titleKey) })} variant="close" icon="close" iconSize={14}
        data-flyout-close onclick={close} />
    </header>
    {/if}
    {#if body.actions}
      <div class="sbr-flyout__actions"><body.actions /></div>
    {/if}
    <div class="sbr-flyout__body">
      {#if body.component && drawnTab}{#key drawnTab.key}<ZonePane {zone} tab={drawnTab} body={pane} />{/key}{/if}
    </div>
  {/if}
</section>

<style>
  @layer components {
    .sbr-flyout {
      position: absolute;
      inset: 0 auto 0 0;
      width: var(--sidebar-flyout-w, 100%);
      display: flex;
      flex-direction: column;
      min-height: 0;
      background: var(--oc-ground-chrome);
      transform: translateX(-100%);
      visibility: hidden;
      pointer-events: none;
      transition: transform var(--sbr-close-ms) ease-in, visibility 0s linear var(--sbr-close-ms);
    }

    .sbr-flyout--open {
      transform: none;
      visibility: visible;
      pointer-events: auto;
      transition: transform var(--sbr-open-ms) ease-out, visibility 0s;
    }

    @media (prefers-reduced-motion: reduce) {
      .sbr-flyout,
      .sbr-flyout--open {
        transition: none;
      }
    }

    :global([data-motion='off']) .sbr-flyout {
      transition: none;
    }

    .sbr-flyout__actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: var(--oc-space-1);
      flex: 0 0 auto;
      min-width: 0;
      padding: var(--oc-space-1) var(--oc-space-2);
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
    }

    .sbr-flyout__body {
      flex: 1 1 auto;
      min-height: 0;
      min-width: 0;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      overflow-x: hidden;
    }
  }
</style>
