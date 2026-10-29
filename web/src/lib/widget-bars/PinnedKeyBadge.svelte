<script lang="ts">
  let { letter, compact = false }: { letter: string; compact?: boolean } = $props();
</script>

{#if letter}<span class="pinned-key-badge" class:pinned-key-badge--compact={compact} data-pinned-key-badge aria-hidden="true">{letter}</span>{/if}

<style>
  @layer components {
    .pinned-key-badge {
      position: absolute;
      bottom: calc(-4px - var(--oc-border, 1px));
      left: calc(-4px - var(--oc-border, 1px));
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      min-width: 12px;
      height: 12px;
      padding: 0 2px;
      border-radius: 1px;
      background: var(--oc-ground-hover);
      box-shadow: 0 0 0 1px var(--oc-line-frame);
      color: var(--oc-orange);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: 1;
      pointer-events: none;
    }

    .pinned-key-badge--compact {
      bottom: calc(-2px - var(--oc-border, 1px));
      left: calc(-2px - var(--oc-border, 1px));
    }
  }
</style>
