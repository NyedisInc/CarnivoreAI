
<script lang="ts">
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import type { Translate } from '../sessions/types';
    import { STATUS_HUES, hueDistance, hueOf, normaliseColorInput } from './account-colors';
    import { LEDGER_KEYS } from './ledger-model';
    import {
        GRID_ROWS,
        PALETTE_GRID,
        XTERM_PALETTE,
        moveIndex,
        paletteIndexOf,
        type PaletteCell,
    } from './xterm-palette';

    interface Props {
        value: string | null;
        onPick: (hex: string | null) => void;
        t: Translate;
        disabled?: boolean;
    }

    const { value, onPick, t, disabled = false }: Props = $props();

    let open = $state(false);
    let initial: string | null = null;
    let place = $state<{ top: number; left: number } | null>(null);
    let chip: HTMLElement | null = $state(null);
    let panel = $state<HTMLElement | null>(null);

    let hot = $state<number | null>(null);
    // svelte-ignore state_referenced_locally
    let tabStop = $state(Math.max(0, paletteIndexOf(value)));
    // svelte-ignore state_referenced_locally
    let draft = $state(value === null ? '' : value.slice(1));

    const chosen = $derived(paletteIndexOf(value));

    $effect(() => {
        if (value !== null && normaliseColorInput(`#${draft.replace(/^#/, '')}`) !== value) {
            draft = value.slice(1);
        }
    });

    const draftValue = $derived(normaliseColorInput(`#${draft.replace(/^#/, '')}`));
    const draftInvalid = $derived(draft !== '' && draftValue === null);

    const nearLed = $derived.by(() => {
        const hue = value === null ? null : hueOf(value);
        return hue !== null && STATUS_HUES.some((led) => hueDistance(hue, led) < 25);
    });

    const pad = (index: number): string => String(index).padStart(3, '0');

    const readout = $derived.by(() => {
        if (hot !== null) {
            const cell = XTERM_PALETTE[hot] as PaletteCell;
            return t(LEDGER_KEYS.colorReadout, { index: pad(cell.index), hex: cell.hex });
        }
        if (value === null) return t(LEDGER_KEYS.colorReadoutNone);
        if (chosen >= 0) {
            return t(LEDGER_KEYS.colorReadout, { index: pad(chosen), hex: value });
        }
        return t(LEDGER_KEYS.colorReadoutCustom, { hex: value });
    });

    function onCellKey(event: KeyboardEvent, index: number): void {
        if (event.key === 'Escape') return;
        const next = moveIndex(index, event.key);
        if (next === index && !event.key.startsWith('Arrow')) return;
        event.preventDefault();
        tabStop = next;
        hot = next;
        const grid = (event.currentTarget as HTMLElement).closest('.ledger-tpick__grid');
        (grid?.querySelector(`[data-idx="${next}"]`) as HTMLElement | null)?.focus();
    }

    const PANEL_W = 420;

    function openPopup(): void {
        initial = value;
        const rect = chip?.getBoundingClientRect();
        const wide = window.innerWidth >= 1024;
        place =
            wide && rect
                ? {
                      top: Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 200)),
                      left: Math.max(8, Math.min(rect.left, window.innerWidth - PANEL_W - 8)),
                  }
                : null;
        open = true;
        hot = null;
    }

    function closePopup(): void {
        open = false;
        hot = null;
        chip?.focus();
    }

    function cancelPopup(): void {
        if (initial !== value) onPick(initial);
        closePopup();
    }

    function onHexInput(raw: string): void {
        draft = raw;
        const hex = normaliseColorInput(`#${raw.replace(/^#/, '')}`);
        if (hex !== null) onPick(hex);
    }
</script>

<div class="ledger-tpick">
    <Button
        bind:element={chip}
        data-ledger="color-chip"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t(LEDGER_KEYS.colorLabel)}
        {disabled}
        onclick={() => (open ? closePopup() : openPopup())}
    >
        <span
            class="ledger-tpick__preview"
            class:ledger-tpick__preview--none={value === null}
            style={value === null ? '' : `--cell: ${value}`}
        ></span>
        <span>{value ?? t(LEDGER_KEYS.colorNone)}</span>
    </Button>

    {#if open}
        
        <AnchoredPopup
            bind:element={panel}
            class={place === null ? 'ledger-tpick__panel ledger-tpick__panel--modal' : 'ledger-tpick__panel'}
            topLayer
            placement="manual"
            style={place ? `top: ${place.top}px; left: ${place.left}px` : ''}
            label={t(LEDGER_KEYS.colorLabel)}
            tabindex={-1}
            anchor={chip}
            initialFocus={`[data-idx="${tabStop}"]`}
            outside="capture"
            onClose={closePopup}
            onEscape={cancelPopup}
        >
            <div class="ledger-tpick__grid" style="--rows: {GRID_ROWS}">
                {#each PALETTE_GRID as cell (cell.index)}
                    <button data-base-exempt="a color swatch: the color is the button"
                        type="button"
                        class="ledger-tcell"
                        class:ledger-tcell--on={chosen === cell.index}
                        style="--cell: {cell.hex}"
                        data-idx={cell.index}
                        tabindex={tabStop === cell.index ? 0 : -1}
                        aria-pressed={chosen === cell.index}
                        aria-label={t(LEDGER_KEYS.colorCellLabel, {
                            index: pad(cell.index),
                            hex: cell.hex,
                        })}
                        {disabled}
                        onmouseenter={() => (hot = cell.index)}
                        onmouseleave={() => (hot = null)}
                        onfocus={() => {
                            hot = cell.index;
                            tabStop = cell.index;
                        }}
                        onblur={() => (hot = null)}
                        onkeydown={(event) => onCellKey(event, cell.index)}
                        onclick={() => {
                            onPick(cell.hex);
                            closePopup();
                        }}
                    ></button>
                {/each}
            </div>

            <div class="ledger-tpick__entry">
                <span
                    class="ledger-tpick__preview"
                    class:ledger-tpick__preview--none={value === null}
                    style={value === null ? '' : `--cell: ${value}`}
                ></span>
                <p class="ledger-tpick__readout" role="status">{readout}</p>
            </div>

            <div class="ledger-tpick__entry">
                <label class="ledger-tpick__hexlabel">
                    <span aria-hidden="true">#</span>
                    <Field
                        data-ledger="color-hex"
                        maxlength={7}
                        autocomplete="off"
                        spellcheck={false}
                        placeholder={t('color.hex.placeholder')}
                        aria-label={t(LEDGER_KEYS.colorHexLabel)}
                        error={draftInvalid ? t(LEDGER_KEYS.colorHexInvalid) : undefined}
                        {disabled}
                        bind:value={draft}
                        oninput={(event) => onHexInput((event.currentTarget as HTMLInputElement).value)}
                        onkeydown={(event) => {
                            if (event.key === 'Enter') {
                                event.preventDefault();
                                closePopup();
                            }
                        }}
                    />
                </label>
                
                <Button
                    size="sm"
                    data-ledger="color-none"
                    aria-pressed={value === null}
                    {disabled}
                    onclick={() => {
                        draft = '';
                        onPick(null);
                        closePopup();
                    }}
                >
                    {t(LEDGER_KEYS.colorNone)}
                </Button>
            </div>

            {#if draftInvalid}
                <p class="ledger-tpick__note">{t(LEDGER_KEYS.colorHexInvalid)}</p>
            {:else if nearLed}
                <p class="ledger-tpick__note">{t(LEDGER_KEYS.colorLedNote)}</p>
            {/if}
        </AnchoredPopup>
    {/if}
</div>

<style>
    .ledger-tpick {
        display: inline-block;
        max-width: 100%;
        font-family: var(--font-mono);
    }

    .ledger-tpick__preview {
        flex: none;
        width: 20px;
        height: 20px;
        border: 1px solid var(--oc-line-panel);
        background: var(--cell);
    }

    .ledger-tpick__preview--none {
        background: transparent;
    }

    :global(.ledger-tpick__panel) {
        position: fixed;
        inset: auto;
        margin: 0;
        z-index: 60;
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-2);
        box-sizing: border-box;
        width: 420px;
        max-width: calc(100vw - 16px);
        max-height: calc(100vh - 16px);
        overflow: auto;
        padding: 10px;
    }

    :global(.ledger-tpick__panel--modal) {
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
    }

    .ledger-tpick__grid {
        display: grid;
        grid-template-rows: repeat(var(--rows), auto);
        grid-auto-flow: column;
        grid-auto-columns: minmax(0, 1fr);
        gap: 1px;
        width: 100%;
    }

    .ledger-tcell {
        --_bd: var(--oc-text-primary);
        aspect-ratio: 1;
        min-width: 0;
        padding: 0;
        border: 1px solid transparent;
        border-radius: 0;
        background: var(--cell);
        cursor: pointer;
    }

    .ledger-tcell:hover:not(:disabled),
    .ledger-tcell--on {
        border-color: var(--oc-text-primary);
    }

    .ledger-tcell:disabled {
        opacity: 0.6;
        cursor: default;
    }

    .ledger-tpick__readout {
        margin: 0;
        min-height: 1.4em;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-hint);
        white-space: pre;
    }

    .ledger-tpick__entry {
        display: flex;
        flex-wrap: wrap;
        gap: var(--oc-space-2);
        align-items: center;
    }

    .ledger-tpick__hexlabel {
        display: inline-flex;
        align-items: center;
        gap: var(--oc-space-1);
        color: var(--oc-text-muted);
    }

    .ledger-tpick__hexlabel :global([data-field]) {
        width: 9ch;
    }

    .ledger-tpick__note {
        margin: 0;
        color: var(--oc-text-secondary);
        font-size: var(--oc-fs-hint);
    }
</style>
