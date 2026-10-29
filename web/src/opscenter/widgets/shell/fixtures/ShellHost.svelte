<script lang="ts">
  import { untrack } from 'svelte';
  import { provideFrameHeader, provideTitlelessHost, type FrameHeader } from '../../../shell/frame-header.svelte';
  import type { WidgetStatus } from '../widget-status';
  import ShellProbe from './ShellProbe.svelte';

  let { hostId = '', titleless = false, onHeader, status = 'ready', note = '', withControls = true, runs = [] }: {
    hostId?: string;
    titleless?: boolean;
    onHeader?: (header: FrameHeader | undefined) => void;
    status?: WidgetStatus;
    note?: string;
    withControls?: boolean;
    runs?: string[];
  } = $props();

  const header = untrack(() => (hostId ? provideFrameHeader(hostId) : undefined));
  if (untrack(() => titleless)) provideTitlelessHost();
  untrack(() => onHeader?.(header));
</script>

<div data-probe-header>{@render header?.action?.()}</div>
<ShellProbe {status} {note} {withControls} {runs} />
