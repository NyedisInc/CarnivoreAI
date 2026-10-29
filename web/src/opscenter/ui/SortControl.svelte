<script lang="ts">
  /* running sessions */
  import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    buttonText,
    menuLabel,
    menu,
  }: {
    buttonText: string;
    menuLabel: string;
    menu: MenuNode[];
  } = $props();

  let anchor = $state<HTMLElement | null>(null);
</script>

<span class="oc-sort-wrap">
  <button
    type="button"
    class="oc-btn oc-btn--tool oc-sort"
    aria-haspopup="menu"
    aria-expanded={anchor !== null}
    onclick={(event) => (anchor = anchor ? null : (event.currentTarget as HTMLElement))}
  >
    {buttonText}
  </button>
  {#if anchor}
    <CascadeMenu root={menu} {anchor} label={menuLabel} onClose={() => (anchor = null)} />
  {/if}
</span>

<style>
  @layer components {
    .oc-sort-wrap {
      position: relative;
      display: inline-flex;
      flex: 0 1 auto;
      min-width: 0;
    }

    .oc-sort {
      min-width: 0;
      margin-left: var(--oc-space-1);
      overflow: hidden;
      text-overflow: ellipsis;
      display: block;
    }
  }
</style>
