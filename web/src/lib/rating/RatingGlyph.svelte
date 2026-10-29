
<script lang="ts">
    interface Props {
        fill?: number;
        size?: number;
    }

    const { fill = 0, size = 14 }: Props = $props();

    const lit = $derived(Number.isFinite(fill) && fill >= 0.5);
</script>

<span class="rg" class:rg--on={lit} style={`--rg-size:${size}px`} aria-hidden="true" data-rating-glyph>*</span>

<style>
  @layer components {
    .rg {
        display: inline-block;
        font-family: var(--font-mono, monospace);
        font-size: var(--rg-size);
        line-height: 1;
        flex: 0 0 auto;
        color: var(--rating-off, var(--oc-line-rule));
    }

    .rg--on {
        color: var(--rating-on, var(--oc-coral));
    }
  }
</style>
