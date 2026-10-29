
<script lang="ts">
    import { heroColors, heroSeed, heroSvg } from './hero-art';

    interface Props { kind: string; name: string }
    const { kind, name }: Props = $props();

    let url = $state<string | null>(null);

    $effect(() => {
        const made = URL.createObjectURL(new Blob([heroSvg(heroSeed(name, kind), kind, heroColors(kind))], { type: 'image/svg+xml' }));
        url = made;
        return () => URL.revokeObjectURL(made);
    });
</script>

{#if url}<img class="pp-card-img" src={url} alt="" draggable="false" />{/if}
