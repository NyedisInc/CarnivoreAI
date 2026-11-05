<script lang="ts">
  import { untrack } from 'svelte';
  import { provideFrameHeader, type FrameHeader } from '../../../shell/frame-header.svelte';
  import Cell from '../Cell.svelte';

  let { instance, onHeader }: { instance: string; onHeader?: (header: FrameHeader) => void } = $props();

  const header = untrack(() => provideFrameHeader('panel-host'));
  untrack(() => onHeader?.(header));
</script>

<div data-host-header>{@render header.action?.()}</div>
<Cell {instance} />
