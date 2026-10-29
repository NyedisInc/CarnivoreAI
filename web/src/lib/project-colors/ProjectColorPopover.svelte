<!-- position: fixed -->
<script lang="ts">
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import type { Translate } from '../sessions/types';
    import { hexToRgb, rgbToHex } from './palette';
    import { hsvToRgb, rgbToHsv } from './hsv';

    interface Props {
        initial: string;
        t: Translate;
        anchor: HTMLElement | null;
        onOk: (hex: string) => void;
        onCancel: () => void;
        onPreview?: (hex: string | null) => void;
    }

    const { initial, t, anchor, onOk, onCancel, onPreview }: Props = $props();

    let hsv = $state<[number, number, number]>(rgbToHsv(...hexToRgb(initial)));
    let box = $state<HTMLElement | null>(null);
    let at = $state({ left: 0, top: 0 });
    const channels = $derived(hsvToRgb(hsv[0], hsv[1], hsv[2]));
    const hex = $derived(rgbToHex(...channels));
    const hueColor = $derived(rgbToHex(...hsvToRgb(hsv[0], 1, 1)));
    const hasEyeDropper = typeof window !== 'undefined' && 'EyeDropper' in window;
    const CHANNELS = ['r', 'g', 'b'] as const;

    function place(): void {
        if (!box || !anchor) return;
        const a = anchor.getBoundingClientRect();
        const w = box.offsetWidth;
        const h = box.offsetHeight;
        at = {
            left: Math.max(8, Math.min(a.left, window.innerWidth - w - 8)),
            top: Math.max(8, Math.min(a.bottom + 6, window.innerHeight - h - 8)),
        };
    }

    let committed = false;

    let frame = 0;

    $effect(() => {
        const color = hex;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => onPreview?.(color));
    });
    $effect(() => () => {
        cancelAnimationFrame(frame);
        if (!committed) onPreview?.(null);
    });

    function confirm(color: string): void {
        committed = true;
        onOk(color);
    }

    function setChannel(index: number, event: Event): void {
        const next = [...channels];
        next[index] = Number((event.currentTarget as HTMLInputElement).value);
        hsv = rgbToHsv(next[0] ?? 0, next[1] ?? 0, next[2] ?? 0, hsv[0]);
    }

    const clamp = (n: number, max: number): number => Math.max(0, Math.min(max, n));

    function dragSquare(event: PointerEvent): void {
        const el = event.currentTarget as HTMLElement;
        if (!el.hasPointerCapture(event.pointerId)) return;
        const r = el.getBoundingClientRect();
        hsv = [hsv[0], clamp((event.clientX - r.left) / r.width, 1), 1 - clamp((event.clientY - r.top) / r.height, 1)];
    }

    function dragHue(event: PointerEvent): void {
        const el = event.currentTarget as HTMLElement;
        if (!el.hasPointerCapture(event.pointerId)) return;
        const r = el.getBoundingClientRect();
        hsv = [clamp((event.clientX - r.left) / r.width, 1) * 360, hsv[1], hsv[2]];
    }

    function startDrag(event: PointerEvent, move: (e: PointerEvent) => void): void {
        (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        move(event);
    }

    function keySquare(event: KeyboardEvent): void {
        const step = event.shiftKey ? 0.1 : 0.01;
        const dx = event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0;
        const dy = event.key === 'ArrowUp' ? step : event.key === 'ArrowDown' ? -step : 0;
        if (!dx && !dy) return;
        event.preventDefault();
        hsv = [hsv[0], clamp(hsv[1] + dx, 1), clamp(hsv[2] + dy, 1)];
    }

    function keyHue(event: KeyboardEvent): void {
        const step = event.shiftKey ? 10 : 1;
        const d = event.key === 'ArrowRight' || event.key === 'ArrowUp' ? step : event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? -step : 0;
        if (event.key === 'Home' || event.key === 'End') hsv = [event.key === 'Home' ? 0 : 360, hsv[1], hsv[2]];
        else if (d) hsv = [clamp(hsv[0] + d, 360), hsv[1], hsv[2]];
        else return;
        event.preventDefault();
    }

    async function sample(): Promise<void> {
        try {
            const picked = await new (window as unknown as { EyeDropper: new () => { open(): Promise<{ sRGBHex: string }> } }).EyeDropper().open();
            hsv = rgbToHsv(...hexToRgb(picked.sRGBHex), hsv[0]);
        } catch {
        }
    }

    function onKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter' && ((event.target as HTMLElement).tagName === 'INPUT' || (event.target as HTMLElement).getAttribute('role') === 'slider')) {
            event.preventDefault();
            event.stopPropagation();
            confirm(hex);
        } else {
            event.stopPropagation();
        }
    }
</script>

<AnchoredPopup
    class="pc-pop"
    tabindex={-1}
    label={t('project.color.custom')}
    data-project-color-popover=""
    {anchor}
    placement="manual"
    style={`left: ${at.left}px; top: ${at.top}px;`}
    onPlace={place}
    initialFocus="[data-pc-square]"
    outside="capture"
    onClose={onCancel}
    bind:element={box}
    onkeydown={onKeydown}
>
    <div class="pc-pop__head">
        <span class="pc-pop__label">{t('project.color.custom')}</span>
    </div>
    <div class="pc-pop__body">
        <div
            class="pc-pop__square"
            role="presentation"
            style:--pc-hue={hueColor}
            data-pc-square-area
            onpointerdown={(e) => startDrag(e, dragSquare)}
            onpointermove={dragSquare}
        >
            <span
                class="pc-pop__handle"
                role="slider"
                tabindex="0"
                data-pc-square
                aria-label={t('project.color.square')}
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={Math.round(hsv[2] * 100)}
                aria-valuetext="{t('project.color.saturation')} {Math.round(hsv[1] * 100)}, {t('project.color.brightness')} {Math.round(hsv[2] * 100)}"
                style:left="{hsv[1] * 100}%"
                style:top="{(1 - hsv[2]) * 100}%"
                onkeydown={keySquare}
            ></span>
        </div>
        <div class="pc-pop__hue" role="presentation" data-pc-hue-area onpointerdown={(e) => startDrag(e, dragHue)} onpointermove={dragHue}>
            <span
                class="pc-pop__handle pc-pop__handle--hue"
                role="slider"
                tabindex="0"
                data-pc-hue
                aria-label={t('project.color.hue')}
                aria-valuemin="0"
                aria-valuemax="360"
                aria-valuenow={Math.round(hsv[0])}
                style:left="{(hsv[0] / 360) * 100}%"
                onkeydown={keyHue}
            ></span>
        </div>
        <div class="pc-pop__row">
            <span class="pc-pop__preview" style:background={hex} data-project-color-preview></span>
            <div class="pc-pop__rgb">
                {#each CHANNELS as name, i (name)}
                    <label class="pc-pop__chan">
                        <span>{name}</span>
                        <input type="number" min="0" max="255" step="1" value={channels[i]} data-channel={name} oninput={(e) => setChannel(i, e)} />
                    </label>
                {/each}
            </div>
            {#if hasEyeDropper}
                <button type="button" class="pc-pop__eye" data-pc-eyedropper aria-label={t('project.color.eyedropper')} onclick={sample}>
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m2 22 1-1h3l9-9M3 21v-3l9-9"/><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3z"/></svg>
                </button>
            {/if}
        </div>
    </div>
    <div class="pc-pop__foot">
        <button type="button" class="modal-btn modal-btn-secondary" data-project-color-cancel onclick={onCancel}>{t('project.color.cancel')}</button>
        <button type="button" class="modal-btn modal-btn-confirm" data-project-color-ok onclick={() => confirm(hex)}>{t('project.color.ok')}</button>
    </div>
</AnchoredPopup>

<style>
    @layer components {
        :global(.pc-pop) {
            position: fixed;
            z-index: 1000;
            width: 16rem;
            max-width: calc(100vw - 16px);
            background: var(--oc-ground-panel);
            color: var(--oc-text-primary);
            font-family: var(--font-mono);
        }

        .pc-pop__head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            height: 2rem;
            padding: 0 var(--oc-space-3);
            background: var(--oc-ground-titlerow);
            box-shadow: 0 1px 0 var(--oc-line-frame);
        }

        .pc-pop__label {
            color: var(--oc-orange);
            font-size: var(--oc-fs-micro);
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .pc-pop__body {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
            padding: var(--oc-space-3);
        }

        .pc-pop__square {
            position: relative;
            height: 8.5rem;
            border: 1px solid var(--oc-line-frame);
            border-radius: 2px;
            background:
                linear-gradient(to bottom, hsl(0 0% 0% / 0), hsl(0 0% 0%)),
                linear-gradient(to right, hsl(0 0% 100%), hsl(0 0% 100% / 0)),
                var(--pc-hue);
            touch-action: none;
            cursor: crosshair;
        }

        .pc-pop__hue {
            position: relative;
            height: 0.75rem;
            border: 1px solid var(--oc-line-frame);
            border-radius: 2px;
            background: linear-gradient(to right, hsl(0 100% 50%), hsl(60 100% 50%), hsl(120 100% 50%), hsl(180 100% 50%), hsl(240 100% 50%), hsl(300 100% 50%), hsl(360 100% 50%));
            touch-action: none;
            cursor: ew-resize;
        }

        .pc-pop__handle {
            position: absolute;
            width: 0.75rem;
            height: 0.75rem;
            transform: translate(-50%, -50%);
            border: 1px solid var(--oc-text-bright);
            border-radius: 50%;
            box-shadow: 0 0 0 1px var(--oc-ground-panel);
            outline: none;
        }

        .pc-pop__handle--hue {
            top: 50%;
            border-radius: 2px;
            width: 0.4rem;
            height: 1.1rem;
        }

        .pc-pop__handle:focus-visible {
            border-color: var(--oc-orange);
        }

        .pc-pop__row {
            display: flex;
            align-items: flex-end;
            gap: var(--oc-space-2);
        }

        .pc-pop__preview {
            flex: none;
            width: 1.9rem;
            height: 1.9rem;
            border: 1px solid var(--oc-line-frame);
            border-radius: 50%;
        }

        .pc-pop__eye {
            flex: none;
            display: grid;
            place-items: center;
            width: 1.9rem;
            height: 1.9rem;
            border: 1px solid var(--oc-line-frame);
            border-radius: 2px;
            background: var(--oc-ground-chrome);
            color: var(--oc-text-secondary);
            cursor: pointer;
        }

        .pc-pop__eye:hover {
            color: var(--oc-text-primary);
        }

        .pc-pop__rgb {
            display: flex;
            flex: 1;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .pc-pop__chan {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-micro);
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }

        .pc-pop__chan input {
            width: 100%;
            min-width: 0;
            padding: 3px 4px;
            border: 1px solid var(--oc-line-frame);
            border-radius: 2px;
            background: var(--oc-ground-chrome);
            color: var(--oc-text-primary);
            font: inherit;
            letter-spacing: 0;
        }

        .pc-pop__foot {
            display: flex;
            justify-content: flex-end;
            gap: var(--oc-space-2);
            padding: var(--oc-space-2) var(--oc-space-3) var(--oc-space-3);
        }
    }
</style>
