
<script lang="ts">
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { clock } from '../../opscenter/lib/frozen-clock.svelte';
    import type { PipelineStatus } from './api';
    import { detailLines, pluginSquares, SQUARE_TONE, squareStateKey, type PluginSquare } from './squares';
    import './pipeline-squares.css';

    interface Props {
        status: PipelineStatus;
        nameOf: (id: string) => string;
        t?: Translate;
        filterable?: boolean;
        selected?: string;
    }
    let { status, nameOf, t = reactiveT, filterable = false, selected = $bindable('') }: Props = $props();

    const uid = $props.id();
    const detailId = `ps-sq-detail-${uid}`;
    const descId = (id: string): string => `ps-sq-desc-${uid}-${id}`;

    let root: HTMLDivElement | undefined = $state();
    let hovered = $state('');
    let focused = $state('');
    let pinned = $state('');

    const nowS = $derived.by(() => {
        void clock.now;
        return Date.now() / 1000;
    });

    const squares = $derived(pluginSquares(status));
    const openId = $derived(hovered || focused || pinned);
    const open = $derived<PluginSquare | null>(squares.find((square) => square.id === openId) ?? null);

    function label(square: PluginSquare): string {
        const state = square.rebuilding ? t('pipeline.plugin.rebuilding') : t(squareStateKey(square.state));
        return t('pipeline.square.label', { plugin: nameOf(square.id), state });
    }

    function described(square: PluginSquare): string {
        return detailLines(square, nowS).map((line) => t(line.key, line.params)).join('; ');
    }

    function closeAll(): void {
        hovered = focused = pinned = '';
    }

    function pointerEnter(event: PointerEvent, id: string): void {
        if (event.pointerType === 'mouse') hovered = id;
    }

    function pointerLeave(event: PointerEvent): void {
        if (event.pointerType === 'mouse') hovered = '';
    }

    function focusIn(event: FocusEvent, id: string): void {
        if (event.target instanceof Element && event.target.matches(':focus-visible')) focused = id;
    }

    function focusOut(event: FocusEvent): void {
        const next = event.relatedTarget;
        if (!(next instanceof Node) || !root?.contains(next)) focused = '';
    }

    function keydown(event: KeyboardEvent): void {
        if (event.key !== 'Escape' || !openId) return;
        closeAll();
        event.stopPropagation();
    }

    function toggle(id: string): void {
        if (filterable) selected = selected === id ? '' : id;
        else if (pinned === id) closeAll();
        else pinned = id;
    }

    function outside(event: PointerEvent): void {
        if (openId && !(event.target instanceof Node && root?.contains(event.target))) closeAll();
    }
</script>

<svelte:document onpointerdown={outside} />

{#if squares.length > 0}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="ps-sq" bind:this={root} data-ps="squares" onpointerleave={pointerLeave} onfocusout={focusOut} onkeydown={keydown}>
        <ul class="ps-sq__row" aria-label={t('pipeline.square.row')}>
            {#each squares as square (square.id)}
                <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
                <li class="ps-sq__item" data-ps-square={square.id} onpointerenter={(event) => pointerEnter(event, square.id)}
                    onfocusin={(event) => focusIn(event, square.id)}>
                    <button data-base-exempt="a status square: the state color is the button" type="button" class="ps-sq__square" data-ps="square" data-state={square.state} data-rebuilding={square.rebuilding}
                        data-selected={filterable && selected === square.id ? 'true' : undefined}
                        aria-label={label(square)} aria-describedby={descId(square.id)}
                        aria-expanded={filterable ? undefined : openId === square.id}
                        aria-pressed={filterable ? selected === square.id : undefined} onclick={() => toggle(square.id)}>
                        <Icon name={square.icon} size={16} />
                        <span class="ps-sq__mark" data-mark={square.state} aria-hidden="true"></span>
                    </button>
                    <span class="oc-visually-hidden" id={descId(square.id)} data-ps="desc">{described(square)}</span>
                    {#if square.rebuilding}<span class="ps-sq__word" data-ps="rebuilding" aria-hidden="true">{t('pipeline.plugin.rebuilding')}</span>{/if}
                </li>
            {/each}
        </ul>
        {#if open}
            <div class="ps-sq__detail" id={detailId} role="tooltip" data-ps="detail" data-ps-detail={open.id}>
                <p class="ps-sq__head">
                    <span class="ps-sq__plugin">{nameOf(open.id)}</span>
                    <span class="ps-state ps-state--{SQUARE_TONE[open.state]}" data-ps="detail-state">{open.rebuilding ? t('pipeline.plugin.rebuilding') : t(squareStateKey(open.state))}</span>
                </p>
                {#each detailLines(open, nowS) as line (line.kind)}
                    <p class="ps-sq__fact" data-ps-fact={line.kind}>{t(line.key, line.params)}</p>
                {/each}
            </div>
        {/if}
    </div>
{/if}
