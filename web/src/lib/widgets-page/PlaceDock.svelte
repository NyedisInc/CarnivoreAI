
<script lang="ts">
    import type { Translate } from '../sessions/types';
    import { PLACES, placeName, type PlaceId } from './places';
    import { drag } from './places-drag.svelte';

    interface Props {
        podium: HTMLElement | undefined;
        place: 'any' | PlaceId;
        boardName: string;
        accept: (place: PlaceId) => 'yes' | 'have' | 'no' | null;
        t: Translate;
        onPick: (place: 'any' | PlaceId) => void;
        onDrop: (widget: string, place: PlaceId) => void;
    }

    const { podium, place, boardName, accept, t, onPick, onDrop }: Props = $props();

    let wrap = $state<HTMLElement | undefined>();
    let docked = $state(false);
    let over = $state<PlaceId | null>(null);

    function scroller(from: HTMLElement): HTMLElement | null {
        for (let node = from.parentElement; node; node = node.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(node).overflowY)) return node;
        }
        return null;
    }

    $effect(() => {
        if (!wrap || !podium || typeof IntersectionObserver === 'undefined') return;
        const host = wrap;
        const watched = podium;
        const root = scroller(host);
        const title = (root ?? document).querySelector<HTMLElement>('.oc-titlebar');
        const top = (): number => (title ? title.offsetHeight : 0);
        host.style.top = `${top()}px`;
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    const edge = (entry.rootBounds ? entry.rootBounds.top : 0) + top() + 8;
                    docked = !entry.isIntersecting && entry.boundingClientRect.bottom < edge;
                }
            },
            { root, threshold: [0, 1] },
        );
        observer.observe(watched);
        const resize = (): void => {
            host.style.top = `${top()}px`;
        };
        window.addEventListener('resize', resize);
        return () => {
            observer.disconnect();
            window.removeEventListener('resize', resize);
        };
    });

    function name(id: 'any' | PlaceId): string {
        return id === 'any' ? t('widgets.places.facet.any') : id === 'board' && place === 'board' && boardName ? t('widgets.places.board.named', { name: boardName }) : placeName(id, t);
    }
</script>

<div class="wp-dockwrap" bind:this={wrap} data-docked={docked ? '' : undefined}>
    <div class="wp-dock">
        <span class="oc-label">{t('widgets.places.dock.label')}</span>
        <div class="oc-seg" role="radiogroup" aria-label={t('widgets.places.dock.label')}>
            {#each ['any', ...PLACES.map((def) => def.id)] as id (id)}
                {@const def = PLACES.find((one) => one.id === id)}
                {@const verdict = def && drag.widget ? accept(def.id) : null}
                <button
                    type="button"
                    class="oc-seg__item wp-chip"
                    class:is-over={over === id}
                    role="radio"
                    aria-checked={place === id}
                    data-place={id}
                    data-accept={verdict ?? undefined}
                    data-pl={def?.id}
                    onclick={() => onPick(id as 'any' | PlaceId)}
                    ondragover={(event) => {
                        if (!def || verdict !== 'yes') return;
                        event.preventDefault();
                        over = def.id;
                    }}
                    ondragleave={() => (over = null)}
                    ondrop={(event) => {
                        event.preventDefault();
                        over = null;
                        const widget = drag.widget;
                        if (def && widget) onDrop(widget, def.id);
                    }}
                >
                    {#if def}<span class="wp-pmark" data-pl={def.id}>{def.mark}</span>{/if}
                    <span>{name(id as 'any' | PlaceId)}</span>
                </button>
            {/each}
        </div>
    </div>
</div>
