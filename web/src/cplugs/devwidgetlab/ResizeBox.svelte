<script lang="ts">
  import type { Snippet } from 'svelte';
  import { onDestroy } from 'svelte';
  import { t } from '../sdk';
  import { dragBox, stepBox, type Box, type ResizeAxis } from './resize-model';

  interface Props {
    box: Box;
    live: Box | null;
    scale: number;
    mode?: 'free' | 'w' | 'n' | 'none';
    onchange: (box: Box, final: boolean) => void;
    onreset: () => void;
    children: Snippet;
  }

  const { box, live, scale, mode = 'free', onchange, onreset, children }: Props = $props();

  const KEY_COMMIT_MS = 400;

  const shown = $derived(live ?? box);
  let drag: { axis: ResizeAxis; x: number; y: number; start: Box; last: Box } | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;

  onDestroy(() => {
    if (timer !== null) clearTimeout(timer);
  });

  function press(event: PointerEvent, axis: ResizeAxis): void {
    if (event.button !== 0) return;
    drag = { axis, x: event.clientX, y: event.clientY, start: shown, last: shown };
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    event.preventDefault();
    (event.currentTarget as HTMLElement).focus({ preventScroll: true });
  }

  function move(event: PointerEvent): void {
    if (!drag) return;
    drag.last = dragBox(drag.start, event.clientX - drag.x, event.clientY - drag.y, drag.axis, scale);
    onchange(drag.last, false);
  }

  function release(): void {
    if (!drag) return;
    const end = drag.last;
    drag = null;
    onchange(end, true);
  }

  function key(event: KeyboardEvent): void {
    if (event.key === 'Home') {
      event.preventDefault();
      event.stopPropagation();
      onreset();
      return;
    }
    const next = stepBox(shown, event.key, event.shiftKey, mode === 'free' || mode === 'none' ? 'se' : mode);
    if (!next) return;
    event.preventDefault();
    event.stopPropagation();
    onchange(next, false);
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => onchange(next, true), KEY_COMMIT_MS);
  }
</script>

<div class="dwl-resize" data-live={live ? 'yes' : 'no'} style:width={live ? `${live.w}px` : undefined} style:height={live ? `${live.h}px` : undefined}>
  {@render children()}
  {#if mode === 'none'}
    
  {:else if mode !== 'free'}
    
    <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
    <div class="dwl-handle dwl-handle--{mode}" role="separator" tabindex="0" aria-orientation={mode === 'w' ? 'vertical' : 'horizontal'}
      aria-label={t(mode === 'w' ? 'cplug.devwidgetlab.resize.width' : 'cplug.devwidgetlab.resize.height')}
      aria-valuenow={mode === 'w' ? shown.w : shown.h} aria-valuetext={t('cplug.devwidgetlab.resize.value', { w: shown.w, h: shown.h })}
      onpointerdown={(event) => press(event, mode)} onpointermove={move} onpointerup={release} onpointercancel={release} onkeydown={key}></div>
  {:else}
  
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <div class="dwl-handle dwl-handle--e" role="separator" tabindex="0" aria-orientation="vertical" aria-label={t('cplug.devwidgetlab.resize.width')}
    aria-valuenow={shown.w} aria-valuetext={t('cplug.devwidgetlab.resize.value', { w: shown.w, h: shown.h })}
    onpointerdown={(event) => press(event, 'e')} onpointermove={move} onpointerup={release} onpointercancel={release} onkeydown={key}></div>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <div class="dwl-handle dwl-handle--s" role="separator" tabindex="0" aria-orientation="horizontal" aria-label={t('cplug.devwidgetlab.resize.height')}
    aria-valuenow={shown.h} aria-valuetext={t('cplug.devwidgetlab.resize.value', { w: shown.w, h: shown.h })}
    onpointerdown={(event) => press(event, 's')} onpointermove={move} onpointerup={release} onpointercancel={release} onkeydown={key}></div>
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <div class="dwl-handle dwl-handle--se" role="separator" tabindex="0" aria-label={t('cplug.devwidgetlab.resize.corner')}
    aria-valuetext={t('cplug.devwidgetlab.resize.value', { w: shown.w, h: shown.h })}
    onpointerdown={(event) => press(event, 'se')} onpointermove={move} onpointerup={release} onpointercancel={release} onkeydown={key}></div>
  {/if}
</div>
