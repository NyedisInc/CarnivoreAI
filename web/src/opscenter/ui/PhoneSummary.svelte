<script lang="ts">
  import type { PhoneSummary } from '../engine/types';

  let { summary }: { summary: PhoneSummary } = $props();
</script>

<span class="oc-psum">
  {#each summary.marks as mark, index (`${mark.tone}-${index}`)}
    <span class="oc-psum-mark" role="img" aria-label={mark.label} title={mark.label}>
      <span
        class="oc-psum-dot"
        class:oc-psum-hollow={mark.shape === 'hollow'}
        style={`--oc-psum-tone: var(--${mark.tone})`}
      ></span>
      {#if mark.count !== null && mark.count !== undefined}<span class="oc-psum-n">{mark.count}</span>{/if}
    </span>
  {/each}
  {#if summary.note}<span class="oc-psum-note">{summary.note}</span>{/if}
</span>

<style>
  @layer components {
    .oc-psum {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
      overflow: hidden;
    }

    .oc-psum-mark {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      flex: 0 0 auto;
    }

    .oc-psum-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--oc-psum-tone);
    }

    .oc-psum-hollow {
      background: none;
      box-shadow: inset 0 0 0 1.5px var(--oc-psum-tone);
    }

    .oc-psum-n {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      font-variant-numeric: tabular-nums;
    }

    .oc-psum-note {
      flex: 0 1 auto;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      font-variant-numeric: tabular-nums;
    }
  }
</style>
