/*  hidden  */
import { untrack } from 'svelte';
import { railSlideout } from '../session-rail/slideout.svelte';
import type { RailEdge } from '../session-rail/rail-model';
import { widgetBars, type BarMode, type BarsTogether } from './bar-settings.svelte';
import { barLead } from './bar-lead.svelte';
import { barState, foldedEdge, realClock, type BarVisual, type Clock } from './bar-state';
import { createPeekCore } from './peek-core.svelte';
import { stripMode } from './bar-pin-action';
import { useStripEscape } from './strip-escape.svelte';

export interface BarVisibilityInput {
  show: boolean;
  mode: BarMode;
  together: BarsTogether;
  drawn: boolean;
  editing: boolean;
  panelShown: boolean;
}

export function createBarVisibility(edge: RailEdge, read: () => BarVisibilityInput, nav: () => HTMLElement | null, clock: Clock = realClock) {
  const core = createPeekCore({ nav, firstKey: '[data-zone-item]', isPeeking: () => state === 'peek', isFolded: () => folded, clock });
  const peek = core.peek;
  const input = $derived.by(() => {
    const raw = read();
    return { ...raw, mode: stripMode(raw.mode) };
  });
  const folded = $derived(foldedEdge(input.together, barLead.edge, edge));
  const state = $derived<BarVisual>(barState({ ...input, folded, ...core.flags }));
  const holds = $derived(input.show && input.drawn && (input.panelShown || input.mode === 'pinned'));

  let heldBefore: boolean | null = null;
  $effect(() => {
    const now = holds;
    untrack(() => {
      if (!now) barLead.release(edge);
      else if (heldBefore === null) barLead.takeIfFree(edge);
      else if (!heldBefore) barLead.takeIfFree(edge);
      heldBefore = now;
    });
  });

  $effect(() => {
    if (!input.show && untrack(() => input.panelShown)) railSlideout.close(edge);
  });

  $effect(() => {
    if (input.together === 'one' && folded && input.panelShown) railSlideout.close(edge);
  });

  let foldWithPanel = false;
  let shownBefore = false;
  $effect(() => {
    const shown = input.panelShown;
    untrack(() => {
      if (shownBefore && !shown) {
        // removed with it
        const focused = document.activeElement;
        if (!focused || !nav()?.contains(focused) || focused.closest('[data-rail-slideout]')) peek.focusOut();
        if (!foldWithPanel && !untrack(() => folded)) peek.panelClosed();
        else peek.escape();
        foldWithPanel = false;
      }
      shownBefore = shown;
    });
  });

  useStripEscape({
    open: () => input.mode !== 'pinned' && (state === 'peek' || state === 'held'),
    hide: () => void close(),
  });

  async function close(): Promise<void> {
    if (state === 'absent' || state === 'edit') return;
    foldWithPanel = input.panelShown;
    railSlideout.close(edge);
    core.fold();
    if (input.mode === 'pinned') await widgetBars.set(edge, { mode: 'autohide' });
  }

  return {
    get state(): BarVisual {
      return state;
    },
    close,
    onpointerenter: core.onpointerenter,
    onpointerleave: core.onpointerleave,
    onfocusin: core.onfocusin,
    onfocusout: core.onfocusout,
    onkeydown: core.onkeydown,
    fold: core.fold,
    onpress: core.onpress,
  };
}
