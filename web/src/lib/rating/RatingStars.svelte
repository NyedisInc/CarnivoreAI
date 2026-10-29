
<script lang="ts">
    import RatingGlyph from './RatingGlyph.svelte';

    interface Props {
        value: number;
        label: string;
        size?: number;
    }

    const { value, label, size = 14 }: Props = $props();
</script>

<span class="rs" role="img" aria-label={label} data-rating-stars style={`font-size:${size}px`}>
    <span class="rs__bracket" aria-hidden="true">[</span>
    {#each [0, 1, 2, 3, 4] as slot}
        <RatingGlyph {size} fill={slot < Math.round(value) ? 1 : 0} />
    {/each}
    <span class="rs__bracket" aria-hidden="true">]</span>
</span>

<style>
  @layer components {
    .rs {
        display: inline-flex;
        align-items: center;
        font-family: var(--font-mono, monospace);
        line-height: 1;
    }

    .rs__bracket {
        color: var(--rating-off, var(--oc-line-rule));
    }
  }
</style>
