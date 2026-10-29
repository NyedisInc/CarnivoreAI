<script lang="ts">
  /*  hidden  */
  import AnchoredPopup from '../../lib/dialog-frame/AnchoredPopup.svelte';
  import WidgetIcon from '../ui/WidgetIcon.svelte';
  import type { LayoutStore } from './layout.svelte';
  import { restoreWithFlight } from './FlyLayer.svelte';
  import { GUTTER } from './tracks';
  import { sizeOf } from './observe.svelte';
  import { resetSurface } from './components-actions';
  import { viewport } from './viewport.svelte';
  import { openWidgets } from '../api/host';
  import type { SlotId } from './types';
  import { enterLayoutEditor } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';

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

  /* height: 100% min-height: 1 padding */
  const room = $derived(sizeOf('content').height);

  const fittable = $derived(store.state.layout.rows.some((row) => row.kind === 'px'));

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

  function onArrangeLayout(): void {
    close();
    enterLayoutEditor();
  }

</script>

<AnchoredPopup
  bind:element={panel}
  class="oc-popover"
  label={t('opscenter.components.title')}
  tabindex={-1}
  {anchor}
  placement="manual"
  style={placement === 'below'
    ? `left: ${Math.round(box.left)}px; top: ${Math.round(box.top)}px; max-height: ${Math.round(box.maxHeight)}px; overflow-y: auto`
    : `left: ${Math.round(box.left)}px; bottom: ${Math.round(box.bottom)}px`}
  onPlace={place}
  initialFocus="button"
  {onClose}
  onEscape={close}
>
  {#if viewport.wide}
    
    <p class="oc-popover-empty" data-layout-editor-pointer>{t('layout_editor.pointer')}</p>
  {:else if hidden.length === 0}
    <p class="oc-popover-empty">{t('opscenter.components.empty')}</p>
  {:else}
    <ul class="oc-popover-list">
      {#each hidden as meta (meta.id)}
        <li>
          <button type="button" class="oc-popover-item" data-btn="row" onclick={() => onRestore(meta.id)}>
            <span class="oc-popover-icon" style={`color: var(--${meta.iconTone})`}>
              <WidgetIcon name={meta.icon} widget={meta.id} size={15} />
            </span>
            <span class="oc-popover-name">{t(meta.titleKey)}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
  {#if viewport.wide}
    <button type="button" class="oc-popover-item oc-popover-arrange" data-btn="row" onclick={onArrangeLayout}
      >{t('opscenter.components.arrange_layout')}</button
    >
  {/if}
  {#if viewport.wide && fittable}
    <button type="button" class="oc-popover-reset" data-btn="row" onclick={onFitRows}
      >{t('opscenter.components.fit_rows')}</button
    >
  {/if}
  <button type="button" class="oc-popover-reset" data-btn="row" onclick={onReset}
    >{t('opscenter.components.reset_layout')}</button
  >
  <button type="button" class="oc-popover-reset" data-btn="row" data-widgets-page onclick={onAllWidgets}
    >{t('opscenter.components.all_widgets')}</button
  >
</AnchoredPopup>

<style>
  @layer components {
    :global(.oc-popover) {
      position: fixed;
      z-index: 45;
      min-width: 204px;
      padding: var(--oc-space-1-5);
      border-radius: var(--oc-radius-sm);
    }

    .oc-popover-empty {
      margin: 0;
      padding: var(--oc-space-2);
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .oc-popover-list {
      margin: 0 0 var(--oc-space-1);
      padding: 0;
      list-style: none;
    }

    .oc-popover-item,
    .oc-popover-reset {
      align-items: center;
      gap: calc(var(--oc-space-2) + var(--oc-space-0-5));
      width: 100%;
      padding: var(--oc-space-1-5) var(--oc-space-2);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }

    .oc-popover-reset {
      border-top: var(--oc-border) solid var(--oc-line-rule);
      border-radius: 0 0 var(--oc-radius-sm) var(--oc-radius-sm);
      color: var(--oc-text-dim);
    }

    .oc-popover-item:disabled {
      cursor: default;
      color: var(--oc-text-dim);
    }

    .oc-popover-arrange {
      margin: var(--oc-space-1) 0 0;
      padding-top: var(--oc-space-1);
      border-top: var(--oc-border) solid var(--oc-line-rule);
    }

    .oc-popover-item:hover,
    .oc-popover-item:focus-visible,
    .oc-popover-reset:hover,
    .oc-popover-reset:focus-visible {
      background: var(--oc-ground-hover);
      color: var(--oc-text-bright);
    }

    .oc-popover-icon {
      display: inline-flex;
      flex: 0 0 auto;
    }

    .oc-popover-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    @media (max-width: 1023px) {
      .oc-popover-item,
      .oc-popover-reset {
        min-height: var(--oc-tap);
      }
  }
  }
</style>
