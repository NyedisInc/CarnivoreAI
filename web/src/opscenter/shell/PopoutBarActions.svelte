<script lang="ts">
  /*  hidden  */
  import Icon from '../ui/Icon.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import { dashboardFromSearch, focusMainWindow, hasMainWindow } from '../../popout/popout';
  import { enterLayoutEditor, layoutEditor } from '../layout-editor/editor.svelte';
  import { viewport } from '../engine/viewport.svelte';

  const board = typeof window !== 'undefined' ? dashboardFromSearch(window.location.search) : null;
  /*  hidden  */
  const canEdit = $derived(board !== null && viewport.wide);
</script>

{#if board !== null && !layoutEditor.active}
  <button
    type="button"
    class="oc-topbar-popout oc-topbar-popout--edit"
    data-popout-edit-layout
    disabled={!canEdit}
    title={canEdit ? t('opscenter.popout.edit_layout_hint') : t('opscenter.popout.edit_layout_narrow')}
    onclick={() => enterLayoutEditor()}
  ><Icon name="layout" size={13} />{t('opscenter.popout.edit_layout')}</button>
{/if}
{#if hasMainWindow()}
  <button type="button" class="oc-topbar-popout" onclick={() => focusMainWindow()}>
    {t('opscenter.popout.focus_main')}
  </button>
{/if}

<style>
  @layer components {
    .oc-topbar-popout {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
      margin-left: var(--oc-space-3);
      padding: var(--oc-space-1) var(--oc-space-2);
      background: none;
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      font: inherit;
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-label);
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .oc-topbar-popout:hover,
    .oc-topbar-popout:focus-visible {
      color: var(--oc-text-primary);
    }

    .oc-topbar-popout--edit {
      --_bd: var(--oc-cyan);
      border-color: var(--oc-cyan);
      color: var(--oc-cyan);
    }

    .oc-topbar-popout--edit:hover {
      color: var(--oc-cyan);
    }

    .oc-topbar-popout--edit:disabled {
      border-color: var(--oc-line-panel);
      color: var(--oc-text-muted);
      cursor: not-allowed;
    }
  }
</style>
