<!-- hidden  box-shadow -->
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import { closeMenuPageGuarded } from './menu-page-shell.svelte';

    interface Props {
        t?: Translate;
    }

    const { t = reactiveT }: Props = $props();

    function openDrawer(): void {
        (globalThis as { SessionSidebar?: { open?: () => void } }).SessionSidebar?.open?.();
    }
</script>

<div class="menu-page-bar" data-oc-base>
  {#if viewport.narrow}
    <button
        type="button"
        class="menu-page-bar__claw menu-page-bar__back"
        aria-label={t('opscenter.components.back')}
        onclick={() => void closeMenuPageGuarded()}
    >
        <Icon name="arrow-left" size={20} strokeWidth={2} />
    </button>
  {:else}
    <button
        type="button"
        class="menu-page-bar__claw"
        aria-label={t('drawer.rail.open')}
        title={t('drawer.rail.open')}
        aria-controls="session-sidebar-panel"
        onclick={openDrawer}
    >
        <img src="/static/img/carnivore/carnivore-mark.png" srcset="/static/img/carnivore/carnivore-mark@2x.png 2x" alt="" />
    </button>
  {/if}
</div>

<style>
    .menu-page-bar {
        position: fixed;
        top: var(--desktop-inset-top, 0px);
        left: 0;
        right: 0;
        height: var(--menu-page-bar-h);
        z-index: 41;
        display: flex;
        align-items: center;
        padding: 0 8px;
        background: var(--oc-ground-titlerow);
        box-shadow: 0 1px 0 var(--oc-line-rule);
    }

    .menu-page-bar__claw {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        padding: 0;
        background: transparent;
        border: var(--oc-border, 1px) solid transparent;
        border-radius: var(--oc-radius);
        cursor: pointer;
    }

    .menu-page-bar__back {
        position: relative;
        color: var(--oc-text-secondary);
    }

    .menu-page-bar__back::after {
        content: '';
        position: absolute;
        inset: -2px;
    }

    .menu-page-bar__back:hover,
    .menu-page-bar__back:focus-visible {
        color: var(--oc-text-primary);
    }

    .menu-page-bar__claw img {
        display: block;
        width: 20px;
        height: 20px;
        object-fit: contain;
        opacity: 0.72;
    }

    .menu-page-bar__claw:hover img {
        opacity: 1;
    }
</style>
