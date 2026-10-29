
<script lang="ts">
    import {
        DETAIL_KEY_STEP,
        DETAIL_MAX_WIDTH,
        DETAIL_MIN_WIDTH,
        clampDetailWidth,
        writeDetailWidth,
    } from './detail-width';

    interface Props {
        width: number;
        label: string;
    }

    let { width = $bindable(), label }: Props = $props();
    let grip: HTMLElement | undefined = $state();
    let dragging = $state(false);
    let grab = 0;

    function container(): DOMRect | null {
        return grip?.closest('.screen__body')?.getBoundingClientRect() ?? null;
    }

    function down(event: PointerEvent): void {
        if (event.button !== 0 || !grip) return;
        const box = container();
        grab = box ? width - (box.right - event.clientX) : 0;
        dragging = true;
        event.preventDefault();
        try { grip.setPointerCapture(event.pointerId); } catch {  }
    }

    function move(event: PointerEvent): void {
        const box = container();
        if (!dragging || !box) return;
        width = clampDetailWidth(box.right - event.clientX + grab, box.width);
    }

    function end(): void {
        if (!dragging) return;
        dragging = false;
        writeDetailWidth(width);
    }

    function key(event: KeyboardEvent): void {
        const box = container();
        const next: Record<string, number> = {
            ArrowLeft: width + DETAIL_KEY_STEP,
            ArrowRight: width - DETAIL_KEY_STEP,
            Home: DETAIL_MIN_WIDTH,
            End: DETAIL_MAX_WIDTH,
        };
        const px = next[event.key];
        if (px === undefined) return;
        event.preventDefault();
        width = clampDetailWidth(px, box?.width ?? 0);
        writeDetailWidth(width);
    }
</script>


<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
    bind:this={grip}
    class="detail-grip"
    class:detail-grip--on={dragging}
    role="separator"
    aria-orientation="vertical"
    aria-label={label}
    aria-valuemin={DETAIL_MIN_WIDTH}
    aria-valuemax={DETAIL_MAX_WIDTH}
    aria-valuenow={width}
    tabindex="0"
    data-detail-grip
    onpointerdown={down}
    onpointermove={move}
    onpointerup={end}
    onpointercancel={end}
    onkeydown={key}
></div>

<style>
    .detail-grip {
        position: absolute;
        top: 0;
        bottom: 0;
        left: 0;
        z-index: 5;
        width: 7px;
        cursor: col-resize;
        touch-action: none;
        background: transparent;
    }

    .detail-grip:hover,
    .detail-grip:focus-visible,
    .detail-grip--on {
        background: linear-gradient(to right, var(--oc-orange) 0, var(--oc-orange) 1px, transparent 1px);
        outline: none;
    }

    @media (max-width: 767px) {
        .detail-grip {
            display: none;
        }
    }
</style>
