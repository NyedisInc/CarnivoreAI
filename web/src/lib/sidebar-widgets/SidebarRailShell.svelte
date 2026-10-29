<script lang="ts">
  import BarPin from '../widget-bars/BarPin.svelte';
  import ZoneHandle from '../zone-shell/ZoneHandle.svelte';
  import { questionPending } from '../approvals/approvals.svelte';
  import { widgetBars } from '../widget-bars/bar-settings.svelte';
  import { barOut, showsHandle, showsPin } from '../widget-bars/bar-state';
  import SidebarRail from './SidebarRail.svelte';
  import RailMenu from './RailMenu.svelte';
  import { onRailShellContextMenu, onRailShellMenuKey } from './rail-menu.svelte';
  import { RAIL_LAYER_ID, setRailPinnedClass } from './rail-dom';
  import { createRailVisibility } from './rail-visibility.svelte';

  let shell = $state<HTMLElement | null>(null);
  const visibility = createRailVisibility(() => shell);
  const look = $derived(visibility.state);

  widgetBars.start();
  $effect(() => setRailPinnedClass(look === 'pinned'));
</script>

{#snippet pin()}
  {#if showsPin(look)}<span class="sbr-shell__pin"><BarPin edge="rail" /></span>{/if}
{/snippet}

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  class="sbr-shell"
  data-rail-state={look}
  bind:this={shell}
  role="presentation"
  onpointerenter={visibility.onpointerenter}
  onpointerleave={visibility.onpointerleave}
  onfocusin={visibility.onfocusin}
  onfocusout={visibility.onfocusout}
  oncontextmenu={onRailShellContextMenu}
  onkeydown={(event) => { onRailShellMenuKey(event); if (!event.defaultPrevented) visibility.onkeydown(event); }}
>
  {#if showsHandle(look)}
    <div class="sbr-shell__handle"><ZoneHandle edge="rail" expanded={look === 'peek'} tone={questionPending() ? 'question' : undefined} controls={RAIL_LAYER_ID} peek={visibility} /></div>
  {/if}
  
  <div class="sbr-shell__layer" id={RAIL_LAYER_ID}>
    {#if look === 'pinned'}<SidebarRail {pin} />{/if}
  </div>
</div>
<RailMenu />

<style>
  @layer components {
    .sbr-shell {
      position: relative;
      width: 100%;
      height: 100%;
    }

    .sbr-shell__handle {
      position: absolute;
      inset: 0;
    }

    .sbr-shell__layer {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 0;
      width: var(--sidebar-rail-w);
      z-index: 3;
      transform: translateX(-100%);
      visibility: hidden;
      transition: transform var(--oc-motion) ease, visibility 0s linear var(--oc-motion);
    }

    .sbr-shell[data-rail-state='pinned'] .sbr-shell__layer {
      position: relative;
      height: 100%;
      transform: none;
      visibility: visible;
      transition: none;
    }

    .sbr-shell__pin {
      display: inline-flex;
    }

    @media (prefers-reduced-motion: reduce) {
      .sbr-shell__layer { transition: none; }
    }
  }
</style>
