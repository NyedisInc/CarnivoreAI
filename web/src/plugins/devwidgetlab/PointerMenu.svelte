<script lang="ts">
  import { CascadeMenu } from '../sdk/ui';
  import type { MenuNode } from '../sdk';
  import { ancestorZoom, counterZoom } from './pointer-zoom';

  interface Props {
    at: { x: number; y: number };
    size?: { w: number; h: number };
    label: string;
    nodes: MenuNode[];
    onclose: () => void;
  }

  const { at, size, label, nodes, onclose }: Props = $props();
  let wrap = $state<HTMLElement | null>(null);
  let marker = $state<HTMLElement | null>(null);
  let ready = $state(false);

  function place(node: HTMLElement): void {
    if (size) {
      node.style.width = `${size.w}px`;
      node.style.height = `${size.h}px`;
    }
    node.style.left = `${at.x}px`;
    node.style.top = `${at.y}px`;
    const box = node.getBoundingClientRect();
    node.style.left = `${at.x - (box.left - at.x)}px`;
    node.style.top = `${at.y - (box.top - at.y)}px`;
  }

  $effect(() => {
    if (ready || !wrap || !marker) return;
    const inverse = counterZoom(ancestorZoom(wrap));
    if (inverse !== null) wrap.style.zoom = String(inverse);
    place(marker);
    ready = true;
  });
</script>

<div class="dwl-pointer-menu" bind:this={wrap}>
  <span class="dwl-tree-menu-anchor" bind:this={marker} aria-hidden="true"></span>
  {#if ready}
    <CascadeMenu root={nodes} anchor={marker} {label} onClose={onclose} />
  {/if}
</div>
