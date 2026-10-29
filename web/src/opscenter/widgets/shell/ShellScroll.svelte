<script lang="ts">
  /*  hidden  overflow: hidden */
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';

  let { children, ...rest }: { children?: Snippet } & HTMLAttributes<HTMLDivElement> = $props();
</script>

<div class="oc-wshell-scroll" {...rest}>{@render children?.()}</div>

<style>
  @layer components {
    .oc-wshell-scroll {
      flex: 1 1 auto;
      height: 100%;
      min-width: 0;
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
    }
  }
</style>
