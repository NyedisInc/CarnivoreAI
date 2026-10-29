<script lang="ts">

  export interface SparkBar {
    h: number;
    tone: string;
  }

  let {
    values = [],
    bars,
    height = 22,
    gap = 2,
    barWidth = 0,
    tone = 'var(--oc-spark)',
  }: {
    values?: number[];
    bars?: readonly SparkBar[];
    height?: number;
    gap?: number;
    barWidth?: number;
    tone?: string;
  } = $props();

  const peak = $derived(Math.max(1, ...values));
</script>

{#if bars}
  <div
    class="oc-spark oc-spark-measured"
    style={`height:${height}px; gap:${gap}px`}
    aria-hidden="true"
  >
    {#each bars as bar, index (index)}
      <span
        class="oc-spark-bar"
        style={`height:${bar.h}px; width:${barWidth}px; background:var(${bar.tone})`}
      ></span>
    {/each}
  </div>
{:else}
  <div class="oc-spark" style={`height:${height}px; gap:${gap}px`} aria-hidden="true">
    {#each values as value, index (index)}
      <span
        class="oc-spark-bar"
        style={`height:${Math.max(8, (value / peak) * 100)}%; background:${tone}; opacity:${(0.35 + 0.65 * (value / peak)).toFixed(3)}`}
      ></span>
    {/each}
  </div>
{/if}

<style>
  @layer components {
    .oc-spark {
      display: flex;
      align-items: flex-end;
      min-width: 0;
    }

    .oc-spark-bar {
      display: block;
      flex: 1 1 0;
      min-width: 2px;
      border-radius: 1px;
    }

    .oc-spark-measured {
      justify-content: flex-end;
    }

    .oc-spark-measured .oc-spark-bar {
      flex: none;
      min-width: 0;
      border-radius: 0;
    }
  }
</style>
