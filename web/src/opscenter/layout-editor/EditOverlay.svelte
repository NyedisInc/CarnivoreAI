<script lang="ts">
</script>

<style>
  @layer components {
    :global(body.oc-layout-editing[data-layout-editing='home'] #launchpad-screen .oc-cellslot[data-slot]:not(.oc-cellslot-zoomed)),
    :global(body.oc-layout-editing[data-layout-editing='terminal'] #terminal-grid .oc-cellslot[data-slot]:not(.oc-cellslot-zoomed)) {
      position: relative;
    }

    :global(body.oc-layout-editing[data-layout-editing='home'] #launchpad-screen .oc-cellslot[data-slot])::after,
    :global(body.oc-layout-editing[data-layout-editing='terminal'] #terminal-grid .oc-cellslot[data-slot])::after {
      content: '';
      position: absolute;
      inset: 0;
      z-index: 60;
      border: 1px dashed var(--oc-cyan);
      pointer-events: none;
    }

    :global(body.oc-layout-editing[data-layout-editing='home'] #launchpad-screen .oc-surface)::after,
    :global(body.oc-layout-editing[data-layout-editing='terminal'] #terminal-grid .oc-surface)::after {
      content: '';
      position: absolute;
      inset: 0;
      z-index: 60;
      border: var(--oc-border) dashed var(--oc-cyan);
      pointer-events: none;
    }

    :global(body.oc-layout-editing[data-layout-editing='home'] #launchpad-screen .oc-gutter:not(.oc-gutter-inert)::before),
    :global(body.oc-layout-editing[data-layout-editing='terminal'] #terminal-grid .oc-gutter:not(.oc-gutter-inert)::before) {
      background: var(--oc-line-rule);
    }
  }
</style>
