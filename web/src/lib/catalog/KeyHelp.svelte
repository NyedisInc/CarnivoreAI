
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
    import type { MenuNode } from '../drawer-tabs/add-component-menu';
    import { CATALOG_KEY_ROWS } from './keys';
    import type { Translate } from '../sessions/types';

    interface Props {
        t: Translate;
    }

    const { t }: Props = $props();

    let open = $state(false);
    let button = $state<HTMLButtonElement | null>(null);

    const nodes = $derived<MenuNode[]>(
        CATALOG_KEY_ROWS.map(([keys, label]): MenuNode => ({ id: `key:${keys}`, label: t(label), hint: keys, run: () => { open = false; } })),
    );
</script>

<div class="keys-menu">
    <button
        type="button"
        class="modal-btn modal-btn-secondary warez-act"
        data-keys-button
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t('warez.keys.button_label')}
        title={t('warez.keys.button_label')}
        bind:this={button}
        onclick={() => { open = !open; }}
    >?</button>
    {#if open}
        <CascadeMenu root={nodes} anchor={button} label={t(BROWSE_KEYS.keysTitle)} alignEnd onClose={() => { open = false; }} />
    {/if}
</div>

<style>
  @layer components {
    .keys-menu {
        position: relative;
        display: inline-flex;
    }
  }
</style>
