<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import Icon from '../ui/Icon.svelte';
  import { DRAWER_VIEW_MODES } from './drawer-view';
  import { widgetDrawerView } from './drawer-view-pref.svelte';

  let {
    pageName,
    docked,
    folded = $bindable(),
  }: { pageName: string; docked: boolean; folded: boolean } = $props();
</script>

<header class="le-titlebar">
  <h2 class="le-title">{t('layout_editor.title')}</h2>
  <span class="le-label">{pageName}</span>
  <div class="le-views" role="group" aria-label={t('layout_editor.view.label')} data-drawer-views>
    {#each DRAWER_VIEW_MODES as mode (mode)}
      <button
        type="button"
        class="le-views__btn"
        class:le-views__btn--on={widgetDrawerView.mode === mode}
        aria-pressed={widgetDrawerView.mode === mode}
        aria-label={t(`layout_editor.view.${mode}`)}
        title={t(`layout_editor.view.${mode}_hint`)}
        data-drawer-view={mode}
        onclick={() => widgetDrawerView.setMode(mode)}
      ><Icon name={mode === 'type' ? 'folder' : 'list'} size={13} /></button>
    {/each}
  </div>
  {#if !docked}<button
    type="button"
    class="le-fold"
    aria-expanded={!folded}
    aria-label={t(folded ? 'layout_editor.drawer.unfold' : 'layout_editor.drawer.fold')}
    title={t(folded ? 'layout_editor.drawer.unfold' : 'layout_editor.drawer.fold')}
    onclick={() => (folded = !folded)}>{folded ? '+' : '-'}</button
  >{/if}
</header>

<style>
  .le-title {
    margin: 0;
    font-size: var(--oc-fs-title, var(--oc-fs-body));
    font-weight: 400;
    letter-spacing: var(--oc-tracking-title, 0.8px);
    text-transform: uppercase;
    color: var(--oc-orange);
    white-space: nowrap;
  }

  .le-label {
    font-size: var(--oc-fs-micro, var(--oc-fs-micro));
    letter-spacing: var(--oc-tracking-label, 0.6px);
    text-transform: uppercase;
    color: var(--oc-text-muted);
  }

  .le-fold {
    margin-left: auto;
    width: 24px;
    height: 24px;
    border: var(--oc-border, 1px) solid var(--oc-line-panel);
    border-radius: var(--oc-radius-sm, 2px);
    background: transparent;
    color: var(--oc-text-secondary);
    font-family: inherit;
    cursor: pointer;
  }
  @layer components {
    .le-views {
      display: inline-flex;
      gap: var(--oc-space-1);
      margin-left: auto;
    }

    .le-views + .le-fold {
      margin-left: var(--oc-space-2);
    }

    .le-views__btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      padding: 0;
      border: var(--oc-border, 1px) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm, 2px);
      background: transparent;
      color: var(--oc-text-muted);
      cursor: pointer;
    }

    .le-views__btn:hover {
      border-color: var(--oc-line-rule);
      color: var(--oc-text-primary);
    }

    .le-views__btn--on {
      border-color: var(--oc-orange-dim);
      background: var(--oc-orange-tint);
      color: var(--oc-orange);
    }
  }
</style>
