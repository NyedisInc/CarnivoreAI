
<script lang="ts">
    import Glyph from '../Glyph.svelte';
    import { resolveIcon } from './icon-model';

    interface Props {
        id: string | null | undefined;
        size?: number;
        /*  hidden  */
        label?: string;
    }

    let { id, size = 16, label }: Props = $props();

    const entry = $derived(resolveIcon(id));
</script>

{#if entry}
    <span
        class="icon-mark"
        data-icon-id={entry.id}
        role={label ? 'img' : undefined}
        aria-label={label || undefined}
        aria-hidden={label ? undefined : 'true'}
    ><Glyph name={entry.glyph} {size} /></span>
{/if}
