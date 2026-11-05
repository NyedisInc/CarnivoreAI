
<script lang="ts">
  import type { HTMLAttributes } from 'svelte/elements';

  interface Props extends Omit<HTMLAttributes<HTMLSpanElement>, 'class' | 'children'> {
    caps: readonly string[];
    hit?: boolean;
    label?: string;
  }

  let { caps, hit = false, label, ...rest }: Props = $props();
</script>

{#if caps.length > 0}
  <span {...rest} class="oc-keycaps" role="img" aria-label={label ?? caps.join(' ')}>
    {#each caps as cap, i (i)}<kbd class={['oc-keycap', hit && 'oc-keycap--hit']} aria-hidden="true">{cap}</kbd>{/each}
  </span>
{/if}
