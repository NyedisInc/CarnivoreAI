<!-- hidden -->
<script lang="ts">
    import { ART_HEIGHT, ART_WIDTH, heroShapes } from './art';
    import { heroImageObjectUrl } from './image-blob';

    interface Props {
        seed: string;
        imageUrl?: string | null;
        shape?: 'banner' | 'square';
        size?: string;
        fit?: 'cover' | 'contain';
        tier?: 'card' | 'banner';
    }

    const { seed, imageUrl = null, shape = 'banner', size = '28px', fit = 'cover', tier = 'card' }: Props = $props();

    const shapes = $derived(heroShapes(seed));
    const wantedSize = $derived(shape === 'square' ? 'thumb' : tier);
    const wantedUrl = $derived(imageUrl ? `${imageUrl}${imageUrl.includes('?') ? '&' : '?'}size=${wantedSize}` : imageUrl);
    let picture = $state<string | null>(null);

    $effect(() => {
        const wanted = wantedUrl;
        let live = true;
        picture = null;
        if (wanted) {
            void heroImageObjectUrl(wanted).then((found) => {
                if (live) picture = found;
            });
        }
        return () => {
            live = false;
        };
    });
</script>

<span class="hero-art hero-art--{shape}" class:hero-art--contain={fit === 'contain' && shape === 'banner' && picture} style={shape === 'square' ? `--hero-art-size:${size}` : undefined} data-hero-art data-hero-source={picture ? 'image' : 'generated'} aria-hidden="true">
    <svg class="hero-art__svg" viewBox="0 0 {ART_WIDTH} {ART_HEIGHT}" preserveAspectRatio="xMidYMid slice" focusable="false">
        {#each shapes as s, i (i)}
            {#if s.kind === 'circle'}
                <circle cx={s.x} cy={s.y} r={s.size} style="fill:var({s.token});opacity:{s.opacity}" />
            {:else if s.kind === 'rect'}
                <rect x={s.x - s.size} y={s.y - s.size} width={s.size * 2} height={s.size * 2} transform="rotate({s.angle} {s.x} {s.y})" style="fill:var({s.token});opacity:{s.opacity}" />
            {:else}
                <rect x={-ART_WIDTH} y={s.y - s.size} width={ART_WIDTH * 3} height={s.size * 2} transform="rotate({s.angle} {s.x} {s.y})" style="fill:var({s.token});opacity:{s.opacity}" />
            {/if}
        {/each}
    </svg>
    {#if picture}<img class="hero-art__img" src={picture} alt="" draggable="false" data-hero-img />{/if}
</span>

<style>
    @layer components {
        .hero-art {
            position: relative;
            display: block;
            overflow: hidden;
            background: var(--oc-ground-raised);
        }

        .hero-art--banner {
            position: absolute;
            inset: 0;
        }

        .hero-art--square {
            flex: none;
            width: var(--hero-art-size, 28px);
            height: var(--hero-art-size, 28px);
            border: 1px solid var(--oc-line-rule);
            border-radius: var(--oc-radius-sm);
            box-sizing: border-box;
        }

        .hero-art__svg,
        .hero-art__img {
            position: absolute;
            inset: 0;
            display: block;
            width: 100%;
            height: 100%;
        }

        .hero-art__img {
            object-fit: cover;
            object-position: center;
        }

        .hero-art--contain {
            background: var(--oc-ground-panel);
        }

        .hero-art--contain .hero-art__svg {
            display: none;
        }

        .hero-art--contain .hero-art__img {
            inset: 0 auto;
            left: 50%;
            width: auto;
            max-width: 100%;
            transform: translateX(-50%);
            object-fit: contain;
            mask-image: linear-gradient(to right, transparent, var(--oc-text-primary) 14%, var(--oc-text-primary) 86%, transparent);
        }
    }
</style>
