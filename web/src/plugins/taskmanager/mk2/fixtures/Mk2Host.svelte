<script lang="ts">
  import type { Component } from 'svelte';
  import { untrack } from 'svelte';
  import { provideFrameHeader } from '../../../sdk/widgets';

  let { cell, props, hostId = 'mk2-host' }: { cell: Component<any>; props: Record<string, unknown>; hostId?: string } = $props();

  untrack(() => provideFrameHeader(hostId));
  const Cell = untrack(() => cell);
</script>

<Cell {...props} />
