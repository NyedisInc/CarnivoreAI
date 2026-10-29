<script lang="ts">
  import BarHandle from '../widget-bars/BarHandle.svelte';
  import type { PinEdge } from '../widget-bars/bar-settings.svelte';

  interface HandlePeek {
    onpress: (kind: 'keyboard' | 'touch' | 'pointer') => void;
  }

  interface HandleDrag {
    begin: (pos: number, extent: number) => void;
    consumeClick: () => boolean;
  }

  let { edge, expanded = false, controls, tone, peek, drag }: {
    edge: PinEdge;
    expanded?: boolean;
    controls?: string;
    tone?: 'question';
    peek?: HandlePeek;
    drag?: HandleDrag;
  } = $props();
</script>

<BarHandle {edge} {expanded} {controls} {tone} onpress={peek ? (kind) => peek.onpress(kind) : undefined}
  ondrag={drag ? (pos) => drag.begin(pos, 0) : undefined} swallowClick={drag ? () => drag.consumeClick() : undefined} />
