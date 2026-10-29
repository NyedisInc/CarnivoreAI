<!-- hidden -->
<script lang="ts">
  import type { Snippet } from 'svelte';

  type Props = { open: boolean; swapKey: string; onWalk: (dir: 1 | -1) => void; children: Snippet };
  let { open, swapKey, onWalk, children }: Props = $props();

  let scroller: HTMLDivElement | undefined = $state();
  let x0: number | null = null;
  let y0: number | null = null;

  $effect(() => {
    void swapKey;
    if (scroller) scroller.scrollTop = 0;
  });

  function start(e: TouchEvent): void {
    if (e.touches.length !== 1) return;
    x0 = e.touches[0]!.clientX;
    y0 = e.touches[0]!.clientY;
  }

  function end(e: TouchEvent): void {
    if (x0 === null || y0 === null) return;
    const touch = e.changedTouches[0];
    const dx = touch ? touch.clientX - x0 : 0;
    const dy = touch ? touch.clientY - y0 : 0;
    x0 = null;
    y0 = null;
    if (Math.abs(dx) > 70 && Math.abs(dy) < 40 && Math.abs(dx) > Math.abs(dy) * 2) onWalk(dx < 0 ? 1 : -1);
  }
</script>


<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="ap-dc" id="ap-dc" data-sheet={open ? 'open' : 'closed'} data-reader-sheet ontouchstart={start} ontouchend={end}>
  <div class="ap-dc-scroll" bind:this={scroller}>
    {#key swapKey}
      <div class="ap-dc-wrap" data-swap>{@render children()}</div>
    {/key}
  </div>
</div>
