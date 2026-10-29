<!-- there is nothing -->
<script lang="ts">
    import {
        GLYPHS,
        GLYPH_SIZE,
        GLYPH_VIEWBOX,
        isWisp,
    } from '../../../client/js/icons/glyphs.js';

    interface Props {
        name: string;
        size?: number;
    }

    let { name, size = GLYPH_SIZE }: Props = $props();

    type GlyphElement = Record<string, string | undefined>;

    const elements = $derived.by(() => {
        const found = (GLYPHS as Record<string, GlyphElement[]>)[name];
        if (!found) {
            console.error('CloudeWeb: no glyph named', name);
            return [];
        }
        return found;
    });
</script>

{#snippet shapes(list: GlyphElement[])}
    
    {#each list as element, index (index)}
        {#if element.tag === 'circle'}
            <circle
                cx={element.cx}
                cy={element.cy}
                r={element.r}
                fill={element.fill}
                stroke={element.stroke}
                stroke-width={element['stroke-width']}
                transform={element.transform}
            />
        {:else if element.tag === 'rect'}
            <rect
                x={element.x}
                y={element.y}
                width={element.width}
                height={element.height}
                rx={element.rx}
                stroke={element.stroke}
                stroke-width={element['stroke-width']}
            />
        {:else}
            <path
                d={element.d}
                stroke={element.stroke}
                stroke-width={element['stroke-width']}
                stroke-linecap={element['stroke-linecap'] as 'round' | undefined}
                stroke-linejoin={element['stroke-linejoin'] as 'round' | undefined}
                stroke-dasharray={element['stroke-dasharray']}
                fill={element.fill}
                transform={element.transform}
                class={element.class}
            />
        {/if}
    {/each}
{/snippet}

{#if elements.some(isWisp)}
    
    <span class="kaw-cup" data-anim-host style:position="relative" style:display="block" style:width="{size}px" style:height="{size}px" style:--kaw-u={size / GLYPH_SIZE}>
        <svg width={size} height={size} viewBox={GLYPH_VIEWBOX} fill="none">{@render shapes(elements.filter((e) => !isWisp(e)))}</svg>
        {#each elements.filter(isWisp) as wisp, i (i)}
            <svg class={wisp.class} style="position:absolute;left:0;top:0" width={size} height={size} viewBox={GLYPH_VIEWBOX} fill="none">{@render shapes([{ ...wisp, class: undefined }])}</svg>
        {/each}
    </span>
{:else}
    <svg width={size} height={size} viewBox={GLYPH_VIEWBOX} fill="none">{@render shapes(elements)}</svg>
{/if}
