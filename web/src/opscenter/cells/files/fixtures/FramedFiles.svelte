<script lang="ts">
  import { untrack } from 'svelte';
  import type { CellProps } from '../../../lib/cell';
  import { provideFrameHeader } from '../../../shell/frame-header.svelte';
  import Cell from '../Cell.svelte';

  let { hostId = '', drawn = false, ...cell }: CellProps & { hostId?: string; drawn?: boolean } = $props();

  const header = untrack(() => (hostId ? provideFrameHeader(hostId) : undefined));
  $effect(() => {
    if (header) header.drawn = drawn;
  });
</script>

<div data-test-header>{@render header?.action?.()}</div>
<Cell {...cell} />
