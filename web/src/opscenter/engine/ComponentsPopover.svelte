<script lang="ts">
  /* the empty state there is nothing */
  import AnchoredPopup from '../../lib/dialog-frame/AnchoredPopup.svelte';
  import WidgetIcon from '../ui/WidgetIcon.svelte';
  import MenuItem from '../../lib/base/MenuItem.svelte';
  import type { LayoutStore } from './layout.svelte';
  import { restoreWithFlight } from './FlyLayer.svelte';
  import { GUTTER } from './tracks';
  import { sizeOf } from './observe.svelte';
  import { resetSurface } from './components-actions';
  import { viewport } from './viewport.svelte';
  import { openWidgets } from '../api/host';
  import type { SlotId } from './types';
  import { t } from '../../lib/i18n/index.svelte';
  import { isDashGridPage } from '../dashgrid/dash-store.svelte';

  let {
    anchor,
    onClose,
    store,
    placement = 'beside',
  }: {
    anchor: HTMLElement | null;
    onClose: () => void;
    placement?: 'beside' | 'below';
    store: LayoutStore;
  } = $props();

  let panel = $state<HTMLElement | null>(null);
  let box = $state({ left: 0, bottom: 0, top: 0, maxHeight: 0 });

  const hidden = $derived(store.hiddenCells());

  const WIDTH = 204;
  const EDGE = 8;

  function place(): void {
    if (!anchor || typeof window === 'undefined') return;
    const rect = anchor.getBoundingClientRect();
    if (placement === 'below') {
      const top = rect.bottom + 4;
      box = {
        left: Math.max(EDGE, Math.min(rect.left, window.innerWidth - WIDTH - EDGE)),
        bottom: 0,
        top,
        maxHeight: Math.max(0, window.innerHeight - top - EDGE),
      };
      return;
    }
    box = {
      left: Math.max(EDGE, Math.min(rect.right - 12, window.innerWidth - WIDTH - EDGE)),
      bottom: Math.max(EDGE, window.innerHeight - rect.bottom),
      top: 0,
      maxHeight: 0,
    };
  }

  function close(): void {
    onClose();
    anchor?.focus();
  }

  function onRestore(id: SlotId): void {
    onClose();
    void restoreWithFlight(store, id);
  }

  const room = $derived(sizeOf('content').height);

  const fittable = $derived(!isDashGridPage(store.page) && store.state.layout.rows.some((row) => row.kind === 'px'));

  function onReset(): void {
    resetSurface(store);
    close();
  }

  /* the widgets page */
  function onAllWidgets(): void {
    close();
    openWidgets();
    (globalThis as { SessionSidebarPin?: { closeAfterSwitch?: () => void } }).SessionSidebarPin?.closeAfterSwitch?.();
  }

  function onFitRows(): void {
    store.fitRows(room, GUTTER);
    store.announce(t('opscenter.components.rows_fitted'));
    close();
  }

  function onAddWidget(): void {
    close();
    document.dispatchEvent(new CustomEvent('oc-widget-drawer-open', { detail: { surface: store.page === 'home' ? 'dashboard' : store.page } }));
  }

</script>

<AnchoredPopup
  bind:element={panel}
  class="oc-popover session-row-menu"
  label={t('opscenter.components.title')}
  tabindex={-1}
  {anchor}
  placement="manual"
  topLayer
  style={placement === 'below'
    ? `left: ${Math.round(box.left)}px; top: ${Math.round(box.top)}px; max-height: ${Math.round(box.maxHeight)}px; overflow-y: auto`
    : `left: ${Math.round(box.left)}px; bottom: ${Math.round(box.bottom)}px`}
  onPlace={place}
  initialFocus="button"
  {onClose}
  onEscape={close}
>
  <div class="session-row-menu__title">{t('opscenter.components.menu_title')}</div>
  <div>
    
    {#if viewport.wide}
      <MenuItem label={t('opscenter.components.add_widget')} onclick={onAddWidget} />
      {#if fittable}
        <div class="session-row-menu__sep" role="separator"></div>
        <MenuItem label={t('opscenter.components.fit_rows')} onclick={onFitRows} />
      {/if}
    {:else if hidden.length === 0}
      <p class="oc-popover-empty">{t('opscenter.components.empty')}</p>
    {:else}
      {#each hidden as meta (meta.id)}
        <MenuItem label={t(meta.titleKey)} onclick={() => onRestore(meta.id)}>
          {#snippet icon()}
            <span class="oc-popover-icon" style={`color: var(--${meta.iconTone})`}>
              <WidgetIcon name={meta.icon} widget={meta.id} size={15} />
            </span>
          {/snippet}
        </MenuItem>
      {/each}
    {/if}
    <div class="session-row-menu__sep" role="separator"></div>
    <MenuItem label={t('opscenter.components.reset_layout')} onclick={onReset} />
    <div class="session-row-menu__sep" role="separator"></div>
    <MenuItem label={t('opscenter.components.all_widgets')} data-widgets-page onclick={onAllWidgets} />
  </div>
</AnchoredPopup>

<style>
  @layer components {
    :global(.oc-popover) {
      position: fixed;
      min-width: 204px;
    }

    .oc-popover-empty {
      margin: 0;
      padding: var(--oc-space-2);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .oc-popover-icon {
      display: inline-flex;
      flex: 0 0 auto;
    }
  }
</style>
