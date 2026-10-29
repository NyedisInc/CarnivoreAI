<script lang="ts">
  import { ratioAfterKey, ratioAtPointer, type SplitAxis } from './split-ratio';

  let {
    axis,
    ratio,
    min,
    max,
    step,
    reset,
    label,
    onpreview,
    oncommit,
  }: {
    axis: SplitAxis;
    ratio: number;
    min: number;
    max: number;
    step: number;
    reset: number;
    label: string;
    onpreview: (ratio: number) => void;
    oncommit: (ratio: number) => void;
  } = $props();

  const bounds = $derived({ min, max, step });
  const at = $derived(`${Math.round(ratio * 1000) / 10}%`);
  let dragging = $state(false);
  let start = 0;
  let latest = 0;

  function container(handle: HTMLElement): DOMRect | null {
    return handle.parentElement?.getBoundingClientRect() ?? null;
  }

  function onpointerdown(event: PointerEvent): void {
    if (event.button !== 0) return;
    dragging = true;
    start = ratio;
    latest = ratio;
    try {
      (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
    } catch {
    }
    event.preventDefault();
  }

  function onpointermove(event: PointerEvent): void {
    if (!dragging) return;
    const box = container(event.currentTarget as HTMLElement);
    if (!box) return;
    latest = ratioAtPointer(axis, event.clientX, event.clientY, box, bounds);
    onpreview(latest);
  }

  function end(): void {
    if (!dragging) return;
    dragging = false;
    oncommit(latest);
  }

  function onkeydown(event: KeyboardEvent): void {
    if (dragging && event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      dragging = false;
      onpreview(start);
      return;
    }
    const next = ratioAfterKey(axis, event.key, ratio, bounds, reset);
    if (next === null) return;
    event.preventDefault();
    event.stopPropagation();
    onpreview(next);
    oncommit(next);
  }
</script>


<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="split-divider"
  class:split-divider--x={axis === 'x'}
  class:split-divider--y={axis === 'y'}
  class:split-divider--dragging={dragging}
  style={axis === 'y' ? `top: ${at}` : `left: ${at}`}
  role="separator"
  tabindex="0"
  aria-orientation={axis === 'y' ? 'horizontal' : 'vertical'}
  aria-label={label}
  aria-valuemin={Math.round(min * 100)}
  aria-valuemax={Math.round(max * 100)}
  aria-valuenow={Math.round(ratio * 100)}
  data-split-divider={axis}
  data-split-at={at}
  {onpointerdown}
  {onpointermove}
  onpointerup={end}
  onpointercancel={end}
  ondblclick={() => {
    onpreview(reset);
    oncommit(reset);
  }}
  {onkeydown}
></div>

<style>
  @layer components {
    .split-divider {
      position: absolute;
      z-index: 3;
      touch-action: none;
      background: transparent;
      outline: none;
    }

    .split-divider::after {
      content: '';
      position: absolute;
      background: var(--oc-line-frame);
      transition: background 120ms ease;
    }

    .split-divider:hover::after,
    .split-divider:focus-visible::after,
    .split-divider--dragging::after {
      background: var(--oc-orange);
    }

    .split-divider--y {
      left: 0;
      right: 0;
      height: 7px;
      margin-top: -3px;
      cursor: ns-resize;
    }

    .split-divider--y::after {
      left: 0;
      right: 0;
      top: 3px;
      height: 2px;
    }

    .split-divider--x {
      top: 0;
      bottom: 0;
      width: 7px;
      margin-left: -3px;
      cursor: ew-resize;
    }

    .split-divider--x::after {
      top: 0;
      bottom: 0;
      left: 3px;
      width: 2px;
    }

    @media (prefers-reduced-motion: reduce) {
      .split-divider::after {
        transition: none;
      }
    }
  }
</style>
