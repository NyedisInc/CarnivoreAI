<script lang="ts">
  let { quiet = false }: { quiet?: boolean } = $props();
</script>

<span class="vchip" class:vchip--quiet={quiet} data-view-chip aria-hidden="true"></span>

<style>
  @layer components {
    .vchip {
      position: absolute;
      left: 0;
      bottom: 0;
      width: var(--oc-space-2);
      height: var(--oc-space-2);
      background: var(--oc-cyan);
      clip-path: polygon(0 0, 0 100%, 100% 100%);
      pointer-events: none;
    }
    .vchip--quiet {
      opacity: 0.45;
    }
  }
</style>
