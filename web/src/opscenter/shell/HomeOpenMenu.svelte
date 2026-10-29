<script lang="ts">
  /* the home screen */
  import IconButton from '../../lib/base/IconButton.svelte';
  import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
  import { t } from '../../lib/i18n/index.svelte';
  import { openTargets } from './open-targets';

  let open = $state(false);
  let button = $state<HTMLElement | null>(null);

  // the home screen
  const root = $derived<MenuNode[]>(
    openTargets().map((target, index, all) => ({
      id: target.id,
      label: target.label,
      sep: index > 0 && target.kind !== all[index - 1]!.kind && target.kind !== 'wallboard',
      run: () => {
        open = false;
        target.open();
      },
    })),
  );
</script>

<div class="oc-open-float">
  <IconButton label={t('opscenter.open.button')} variant="float" icon="external" iconSize={13} data-home-open
    aria-haspopup="menu" aria-expanded={open} bind:element={button} onclick={() => (open = !open)} />
</div>

{#if open}
  <CascadeMenu {root} anchor={button} label={t('opscenter.open.menu')} onClose={() => (open = false)} />
{/if}

<style>
  @layer components {
    .oc-open-float {
      position: absolute;
      top: var(--oc-space-1);
      right: var(--oc-space-3);
      z-index: 5;
      pointer-events: none;
    }

    .oc-open-float :global([data-home-open]) {
      pointer-events: auto;
    }
  }
</style>
