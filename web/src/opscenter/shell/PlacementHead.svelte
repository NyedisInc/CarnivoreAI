<script lang="ts">
  import CornerMenu from './CornerMenu.svelte';
  import WidgetHead from './WidgetHead.svelte';
  import type { CellMeta } from '../engine/types';
  import type { FrameHeader } from './frame-header.svelte';
  import type { MenuSlot } from './widget-head';
  import type { Snippet } from 'svelte';

  let {
    meta,
    header,
    title,
    count = null,
    icon = null,
    shown,
    onRemove,
    menu,
    phone = false,
  }: {
    meta: CellMeta;
    header: FrameHeader;
    title: string;
    count?: number | null;
    icon?: string | null;
    shown: boolean;
    onRemove: (() => void) | null;
    menu: Snippet<[MenuSlot]>;
    phone?: boolean;
  } = $props();

  let open = $state(false);
  let anchor = $state<HTMLElement | null>(null);
</script>

{#snippet corner()}
  <CornerMenu {meta} {title} {icon} editing={false} place="row" {phone} {menu} bind:open bind:anchor />
{/snippet}

{#if shown}
  <WidgetHead {meta} {header} {title} {count} {corner} tap={phone} onClose={onRemove && !phone ? () => onRemove() : null} withRight={false} />
{/if}
