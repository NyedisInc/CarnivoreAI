
<script lang="ts">
    import type { Snippet } from 'svelte';
    import type { Translate } from '../sessions/types';
    import KindMark from './KindMark.svelte';
    import './warez-card.css';

    interface Props {
        kind: string | null;
        t: Translate;
        name: string | null;
        brief?: string | null;
        onOpen?: (() => void) | null;
        selected?: boolean;
        installed?: boolean;
        untrusted?: boolean;
        itemId?: string;
        plain?: boolean;
        thumb: Snippet;
        act?: Snippet;
        beside?: Snippet;
        flags?: Snippet;
        children?: Snippet;
    }

    const { kind, t, name, brief = null, onOpen = null, selected = false, installed = false, untrusted = false, itemId = undefined, plain = false, thumb, act, beside, flags, children }: Props = $props();

    const kindMod = $derived(kind && /^[a-z]+$/.test(kind) ? kind : 'unknown');

    function rowClick(event: MouseEvent): void {
        if (!onOpen) return;
        const target = event.target as HTMLElement | null;
        if (target?.closest('button, a, select, input, label, [role="menu"], [role="switch"]')) return;
        onOpen();
    }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
<article
    class="catalog-card kind-band kind-band--{kindMod}"
    class:catalog-card--untrusted={untrusted}
    data-kind={kindMod}
    data-item-id={itemId}
    data-installed={installed ? 'true' : 'false'}
    aria-current={selected ? 'true' : undefined}
    onclick={rowClick}
>
    <div class="catalog-card__media">
        <div class="catalog-card__thumb" class:catalog-card__thumb--plain={plain} data-card-media>{@render thumb()}</div>
    </div>
    <div class="catalog-card__ct">
        <div class="catalog-card__head">
            <span class="catalog-card__name">
                <KindMark {kind} size="md" {t} />
                {#if name}
                    {#if onOpen}
                        <button type="button" class="catalog-card__title catalog-card__open" onclick={onOpen}>{name}</button>
                    {:else}
                        <span class="catalog-card__title">{name}</span>
                    {/if}
                {/if}
                {@render beside?.()}
            </span>
            <span class="catalog-card__slot">{@render act?.()}</span>
        </div>
        {#if flags}<div class="catalog-card__flags">{@render flags()}</div>{/if}
        <p class="catalog-card__brief">{brief ?? ''}</p>
        {@render children?.()}
    </div>
</article>
