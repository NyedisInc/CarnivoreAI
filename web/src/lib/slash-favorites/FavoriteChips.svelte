
<script lang="ts">
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import { tick } from 'svelte';
    import { t } from '../i18n/index.svelte';
    import {
        FAVORITE_COLORS,
        indexAtPoint,
        keyboardDelta,
        moveItem,
        sameOrder,
        swatchVar,
        type Favorite,
        type FavoriteColor,
        type Rect,
    } from './favorites-model';
    import { reorderFavorites, setFavoriteColor, unstarFavorite, type WriteResult } from './favorites-api';
    import { favoritesState, payloadFromRow, setFavoritesRow } from './favorites-store.svelte';

    interface Props {
        onSelect: (command: string) => void;
        onChange: (payload: ReturnType<typeof payloadFromRow>) => void;
        describe: (command: string) => string;
    }

    const { onSelect, onChange, describe }: Props = $props();

    let arranging = $state(false);
    let picking = $state<string | null>(null);
    let busy = $state(false);
    let notice = $state('');
    let preview = $state<Favorite[] | null>(null);
    let dragging = $state<string | null>(null);
    let grid = $state<HTMLElement | null>(null);

    const row = $derived(favoritesState.row);
    const shown = $derived(preview ?? row.favorites);
    const pickingFavorite = $derived(
        picking === null ? null : (row.favorites.find((f) => f.command === picking) ?? null),
    );

    function apply(result: WriteResult): void {
        if (result.kind === 'failed') {
            notice = t('slash.favorites.failed', { reason: result.message });
            return;
        }
        setFavoritesRow(result.row);
        notice = result.kind === 'stale' ? t('slash.favorites.stale') : '';
        if (picking !== null && !result.row.favorites.some((f) => f.command === picking)) picking = null;
        onChange(payloadFromRow(result.row));
    }

    async function run(write: () => Promise<WriteResult>): Promise<void> {
        busy = true;
        try {
            apply(await write());
        } finally {
            busy = false;
            preview = null;
        }
    }

    async function commitOrder(order: string[]): Promise<void> {
        if (sameOrder(order, row.favorites.map((f) => f.command))) {
            preview = null;
            return;
        }
        await run(() => reorderFavorites(order));
    }

    function onChipClick(command: string): void {
        if (dragging !== null) return;
        if (arranging) {
            picking = picking === command ? null : command;
            return;
        }
        onSelect(command);
    }

    async function onChipKey(event: KeyboardEvent, index: number): Promise<void> {
        const delta = keyboardDelta(event.key, event.altKey);
        if (delta === 0 || busy) return;
        event.preventDefault();
        const favorites = row.favorites;
        const moving = favorites[index];
        if (!moving) return;
        const next = moveItem(favorites, index, index + delta);
        preview = next;
        await commitOrder(next.map((f) => f.command));
        await tick();
        const buttons = grid ? [...grid.querySelectorAll<HTMLButtonElement>('.command-button')] : [];
        buttons.find((button) => button.dataset.command === moving.command)?.focus();
    }

    function chipRects(): Rect[] {
        if (!grid) return [];
        return [...grid.querySelectorAll('.command-chip')].map((el) => el.getBoundingClientRect());
    }

    function onGripDown(event: PointerEvent, command: string): void {
        if (busy) return;
        event.preventDefault();
        dragging = command;
        preview = row.favorites.slice();
        const target = event.currentTarget as Element & { setPointerCapture?: (id: number) => void };
        if (typeof target.setPointerCapture === 'function' && event.pointerId !== undefined) {
            try {
                target.setPointerCapture(event.pointerId);
            } catch {
            }
        }
    }

    function onGripMove(event: PointerEvent): void {
        if (dragging === null || preview === null) return;
        const to = indexAtPoint(chipRects(), event.clientX, event.clientY);
        const from = preview.findIndex((f) => f.command === dragging);
        if (to >= 0 && from >= 0 && to !== from) preview = moveItem(preview, from, to);
    }

    async function onGripUp(): Promise<void> {
        if (dragging === null || preview === null) return;
        const order = preview.map((f) => f.command);
        dragging = null;
        await commitOrder(order);
    }

    function onGripCancel(): void {
        dragging = null;
        preview = null;
    }

    function pickColor(command: string, color: FavoriteColor | null): void {
        if (busy) return;
        void run(() => setFavoriteColor(command, color));
    }

    function unstar(event: MouseEvent, command: string): void {
        event.stopPropagation();
        if (busy) return;
        void run(() => unstarFavorite(command));
    }

    function toggleArrange(): void {
        arranging = !arranging;
        if (!arranging) picking = null;
    }
</script>

{#if row.favorites.length === 0}
    <div class="common-commands-empty">{t('slash.favorites.empty')}</div>
{:else}
    <div class="fav-bar">
        {#if row.defaulted}
            <div class="common-commands-note">{t('slash.favorites.defaulted')}</div>
        {/if}
        <Button
            size="sm"
            data-fav-arrange
            aria-pressed={arranging}
            onclick={toggleArrange}
        >{arranging ? t('slash.favorites.done') : t('slash.favorites.arrange')}</Button>
    </div>

    <div
        class="common-commands-chips"
        class:fav-arranging={arranging}
        role="list"
        aria-label={t('slash.favorites.label')}
        bind:this={grid}
    >
        {#each shown as fav, index (fav.command)}
            <div
                class="command-chip"
                class:command-chip--dragging={dragging === fav.command}
                class:command-chip--marked={fav.color !== null}
                role="listitem"
                data-command={fav.command}
                data-fav-color={fav.color ?? ''}
                style:--fav-mark={fav.color === null ? null : swatchVar(fav.color)}
            >
                {#if arranging}
                    <IconButton
                        label={t('slash.favorites.drag', { command: fav.command })}
                        variant="quiet"
                        data-fav-grip
                        disabled={busy}
                        onpointerdown={(event) => onGripDown(event, fav.command)}
                        onpointermove={onGripMove}
                        onpointerup={onGripUp}
                        onpointercancel={onGripCancel}
                    ><span aria-hidden="true"></span></IconButton>
                {/if}
                <button
                    type="button"
                    class="command-button"
                    data-command={fav.command}
                    aria-expanded={arranging ? picking === fav.command : undefined}
                    onclick={() => onChipClick(fav.command)}
                    onkeydown={(event) => onChipKey(event, index)}
                >
                    <span class="command-button-name">{fav.command}</span>
                    {#if fav.description}
                        <span class="command-button-desc">{fav.description}</span>
                    {/if}
                </button>
                <IconButton
                    label={t('slash.favorites.unstar', { command: fav.command })}
                    variant="quiet"
                    pressed={true}
                    data-fav-star
                    disabled={busy}
                    onclick={(event) => unstar(event, fav.command)}
                >
                    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">
                        <path
                            d="M12 3.6l2.5 5.06 5.58.81-4.04 3.94.95 5.56L12 16.35l-4.99 2.62.95-5.56L3.92 9.47l5.58-.81z"
                            fill="currentColor"
                            stroke="currentColor"
                            stroke-width="1.6"
                            stroke-linejoin="round"
                        />
                    </svg>
                </IconButton>
            </div>
        {/each}
    </div>

    {#if arranging && pickingFavorite}
        <div
            class="fav-swatches"
            role="group"
            aria-label={t('slash.favorites.color_for', { command: pickingFavorite.command })}
        >
            <span class="fav-swatches__label">{t('slash.favorites.color_for', { command: pickingFavorite.command })}</span>
            {#each FAVORITE_COLORS as color (color)}
                <button
                    type="button"
                    class="fav-swatch"
                    data-color={color}
                    style:--fav-swatch={swatchVar(color)}
                    aria-pressed={pickingFavorite.color === color}
                    aria-label={t(`slash.favorites.color.${color}`)}
                    title={t(`slash.favorites.color.${color}`)}
                    disabled={busy}
                    onclick={() => pickColor(pickingFavorite.command, color)}
                ></button>
            {/each}
            <button
                type="button"
                class="fav-swatch fav-swatch--none"
                data-color=""
                aria-pressed={pickingFavorite.color === null}
                aria-label={t('slash.favorites.color.none')}
                title={t('slash.favorites.color.none')}
                disabled={busy}
                onclick={() => pickColor(pickingFavorite.command, null)}
            ></button>
        </div>
    {/if}
{/if}

{#if notice}
    <div class="fav-notice" role="status">{notice}</div>
{/if}

<style>
    .fav-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 8px;
    }

    .fav-bar :global(.common-commands-note) {
        margin-bottom: 0;
        text-align: left;
    }

    .fav-bar :global([data-fav-arrange]) {
        margin-left: auto;
    }

    .command-chip--marked::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 4px;
        background: var(--fav-mark);
        z-index: 1;
        pointer-events: none;
    }

    .command-chip--dragging {
        opacity: 0.55;
        outline: 1px dashed var(--oc-orange);
    }

    .command-chip :global([data-fav-grip]) {
        --_btn-h: 44px;
        flex: 0 0 22px;
        width: 22px;
        height: auto;
        cursor: grab;
        touch-action: none;
    }

    .command-chip :global([data-fav-star]) {
        --oc-ibtn-size: 44px;
        position: absolute;
        top: 0;
        right: 0;
        width: 44px;
        height: 44px;
        z-index: 1;
    }

    .command-chip :global([data-fav-grip] span) {
        width: 8px;
        height: 14px;
        background-image: radial-gradient(currentColor 1.2px, transparent 1.4px);
        background-size: 4px 4.6px;
    }

    .fav-arranging .command-button-name {
        max-width: 100%;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        overflow-wrap: normal;
        word-break: normal;
    }

    .fav-arranging .command-chip--dragging :global([data-fav-grip]) {
        cursor: grabbing;
    }

    .fav-swatches {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        margin-top: 10px;
        padding: 8px 10px;
        border: var(--oc-border) solid var(--oc-line-panel);
        border-radius: var(--oc-radius-sm);
        background: var(--oc-ground-field);
    }

    .fav-swatches__label {
        color: var(--oc-text-muted);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        margin-right: 4px;
    }

    .fav-swatch {
        width: 32px;
        height: 32px;
        min-width: 32px;
        padding: 0;
        border: var(--oc-border) solid var(--oc-line-rule);
        border-radius: var(--oc-radius-sm);
        background: var(--fav-swatch);
        cursor: pointer;
    }

    .fav-swatch--none {
        background: transparent;
        border-style: dashed;
    }

    .fav-swatch[aria-pressed='true'] {
        border-color: var(--oc-text-bright);
        box-shadow: 0 0 0 2px var(--oc-orange);
    }

    .fav-swatch:disabled {
        opacity: 0.5;
        cursor: default;
    }

    .fav-notice {
        margin-top: 8px;
        color: var(--oc-yellow);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
        text-align: center;
    }
</style>
