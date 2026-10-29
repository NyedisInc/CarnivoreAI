<script lang="ts">
  import IconButton from '../base/IconButton.svelte';
  import CascadeMenu from './CascadeMenu.svelte';
  import type { MenuNode } from './add-component-menu';
  import { t } from '../i18n/index.svelte';
  import { viewMenuNodes } from '../session-list/view-choices';
  import { viewState, watchViewState } from '../session-list/view-state.svelte';

  let open = $state(false);
  let button = $state<HTMLElement | null>(null);

  $effect(() => watchViewState());

  function toggle(): void {
    open = !open;
  }

  const root = $derived<MenuNode[]>(viewMenuNodes());

  const label = $derived(t('drawer.action.density', { mode: t(`drawer.density.${viewState.density}`) }));
</script>

<IconButton {label} variant="quiet" data-action="density" data-density={viewState.density} aria-haspopup="menu"
  aria-expanded={open} bind:element={button} onclick={toggle}>
  
  <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <rect x="3" y="4" width="18" height="5" rx="1.5" />
    <rect x="3" y="11.25" width="18" height="3.5" rx="1.2" />
    <rect x="3" y="17" width="18" height="2" rx="1" />
  </svg>
</IconButton>

{#if open}
  <CascadeMenu {root} anchor={button} label={t('drawer.density.menu')} onClose={() => (open = false)} />
{/if}

<style>
  @layer components {
    :global([data-btn][data-action='density']) {
      --oc-ibtn-size: 28px;
      border-radius: var(--oc-radius-sm);
      color: var(--oc-text-secondary);
    }

    :global([data-btn][data-action='density']:hover:not(:disabled)),
    :global([data-btn][data-action='density'][aria-expanded='true']) {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
    }
  }
</style>
