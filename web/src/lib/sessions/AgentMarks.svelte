<script lang="ts">
  import type { Snippet } from 'svelte';
  import { sessionMark } from './agent-marks';

  let { family, icon = null, light }: { family: string | null; icon?: string | null; light?: Snippet } = $props();

  const mark = $derived(sessionMark(family, icon));
</script>

<span class="agent-marks" data-agent-marks="">
  {@render light?.()}
  <span class="agent-marks-provider" data-agent-family={mark.key} role="img" aria-label={mark.label} title={mark.label}
    >{@html mark.svg}</span
  >
</span>

<style>
  .agent-marks {
    display: inline-flex;
    flex: none;
    align-items: center;
    gap: 6px;
  }

  .agent-marks-provider {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    flex: none;
    line-height: 0;
    color: var(--oc-text-secondary);
  }

  .agent-marks-provider[data-agent-family='unknown'] {
    color: var(--oc-text-muted);
    opacity: 0.6;
  }
</style>
