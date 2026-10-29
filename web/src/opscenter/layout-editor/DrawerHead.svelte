<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import IconButton from '../../lib/base/IconButton.svelte';
  import Icon from '../ui/Icon.svelte';
  import { DRAWER_VIEW_MODES } from './drawer-view';
  import { widgetDrawerView } from './drawer-view-pref.svelte';

  let {
    pageName,
    docked,
    folded = $bindable(),
  }: { pageName: string; docked: boolean; folded: boolean } = $props();

  const resolvedMode = widgetDrawerView.mode;
  void resolvedMode;
</script>

<header class="le-titlebar">
  <h2 class="le-title">{t('layout_editor.title')}</h2>
  <span class="le-label">{pageName}</span>
  <div class="le-views" role="group" aria-label={t('layout_editor.view.label')} data-drawer-views>
    {#each DRAWER_VIEW_MODES as mode (mode)}
      <IconButton
        label={t(`layout_editor.view.${mode}_hint`)}
        variant="quiet"
        pressed={widgetDrawerView.mode === mode}
        data-drawer-view={mode}
        onclick={() => widgetDrawerView.setMode(mode)}
      ><Icon name={mode === 'type' ? 'folder' : 'list'} size={13} /></IconButton>
    {/each}
  </div>
  {#if !docked}<IconButton
    label={t(folded ? 'layout_editor.drawer.unfold' : 'layout_editor.drawer.fold')}
    variant="quiet"
    data-drawer-fold=""
    aria-expanded={!folded}
    onclick={() => (folded = !folded)}>{folded ? '+' : '-'}</IconButton
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

  [data-drawer-fold] {
    --_btn-ink: var(--oc-text-dim);
    margin-left: auto;
  }
  @layer components {
    .le-views {
      display: inline-flex;
      gap: var(--oc-space-1);
      margin-left: auto;
    }

    .le-views + [data-drawer-fold] {
      margin-left: var(--oc-space-2);
    }
  }
</style>
