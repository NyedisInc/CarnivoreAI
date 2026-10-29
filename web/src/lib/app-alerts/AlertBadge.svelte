<script lang="ts">
  /* position: relative */
  import { badgeOf } from '../attention-kinds/bell-badge';
  import { bellRows } from '../attention-kinds/read.svelte';

  const badge = $derived(badgeOf(bellRows()));
</script>

{#if badge.severity}
  <span class="aa-badge" class:aa-badge--error={badge.severity === 'error'}
    class:aa-badge--warn={badge.severity === 'warn'} data-app-alert-badge={badge.severity}>{badge.count}</span>
{/if}

<style>
  @layer components {
  .aa-badge {
    position: absolute;
    top: -3px;
    right: -5px;
    min-width: 14px;
    height: 14px;
    padding: 0 3px;
    box-sizing: border-box;
    border: var(--oc-border, 1px) solid currentColor;
    border-radius: var(--oc-radius-sm, 2px);
    background: var(--oc-ground-chrome);
    font-family: var(--font-mono);
    font-size: 9px;
    line-height: 12px;
    text-align: center;
    pointer-events: none;
  }
  .aa-badge--error { color: var(--oc-coral); }
  .aa-badge--warn { color: var(--oc-yellow); }
  }
</style>
