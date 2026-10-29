<script lang="ts">
  import { MARKER_PATH, MARKER_TOKEN, type MarkerId } from './task-manager-markers';

  let { id, size = 8, label = undefined }: { id: MarkerId; size?: number; label?: string } = $props();
</script>

<svg class="hdm" width={size} height={size} viewBox="0 0 10 10" style:--_marker={MARKER_TOKEN[id]} data-task-manager-marker={id}
     role={label ? 'img' : undefined} aria-label={label} aria-hidden={label ? undefined : 'true'}>
  {#if label}<title>{label}</title>{/if}
  <path d={MARKER_PATH[id]} fill="currentColor" />
</svg>

<style>
  @layer components {
    .hdm {
      flex: none;
      color: var(--_marker);
    }
  }
</style>
