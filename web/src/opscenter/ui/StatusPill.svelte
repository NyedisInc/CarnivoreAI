<script lang="ts">
  let {
    tone = 'var(--oc-green)',
    label,
    showLabel = true,
    dot = false,
    shape = 'solid',
  }: {
    tone?: string;
    label: string;
    showLabel?: boolean;
    dot?: boolean;
    shape?: 'solid' | 'hollow';
  } = $props();
</script>

{#if dot}
  <span
    class="oc-pill-mark"
    class:oc-pill-hollow={shape === 'hollow'}
    style={`--oc-pill-tone: ${tone}`}
    role="img"
    aria-label={label}
    title={label}
  ></span>
{:else}
  <span class="oc-pill" title={showLabel ? undefined : label}>
    <span class="oc-pill-dot" style={`background:${tone}`}></span>
    {#if showLabel}
      <span class="oc-pill-text" style={`color:${tone}`}>{label}</span>
    {:else}
      <span class="oc-visually-hidden">{label}</span>
    {/if}
  </span>
{/if}

<style>
  @layer components {
    .oc-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
    }

    .oc-pill-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex: 0 0 auto;
    }

    .oc-pill-text {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .oc-pill-mark {
      display: inline-block;
      flex: 0 0 auto;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--oc-pill-tone);
    }

    .oc-pill-hollow {
      background: none;
      box-shadow: inset 0 0 0 2px var(--oc-pill-tone);
    }
  }
</style>
