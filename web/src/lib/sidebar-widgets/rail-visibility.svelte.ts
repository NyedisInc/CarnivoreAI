import { barState, realClock, type BarVisual, type Clock } from '../widget-bars/bar-state';
import { widgetBars } from '../widget-bars/bar-settings.svelte';
import { createPeekCore } from '../widget-bars/peek-core.svelte';
import { barPinned } from '../widget-bars/bar-pin-action';
import { useStripEscape } from '../widget-bars/strip-escape.svelte';
import { activeFlyout, closeFlyout, openFlyout } from './flyout.svelte';
import { modalShowing } from './escape-guards';
import { FLYOUT_CONTAINER_ID, RAIL_LAYER_ID } from './rail-dom';
import { MENU_FLYOUT } from './widget-ids';

const BAR_SLOT_ID = 'session-sidebar-bar-slot';
const FIRST_KEY = '[data-rail-key][tabindex="0"]';

export function createRailVisibility(nav: () => HTMLElement | null, clock: Clock = realClock) {
  const inMenu = (node: Node): boolean => document.getElementById(FLYOUT_CONTAINER_ID)?.contains(node) === true;
  const over = (el: Element | null | undefined, x: number, y: number): boolean => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return x >= r.left && x < r.right && y >= r.top && y < r.bottom;
  };
  const flyoutHoldsRail = (): boolean => state === 'peek' || activeFlyout() === MENU_FLYOUT;
  const inside = (x: number, y: number): boolean =>
    !modalShowing(document) && (over(nav(), x, y) ||
    (state === 'peek' && over(document.getElementById(RAIL_LAYER_ID), x, y)) ||
    (flyoutHoldsRail() && document.querySelector('.sbr-flyout--open') !== null && over(document.getElementById(FLYOUT_CONTAINER_ID)?.querySelector('.sbr-flyout--open'), x, y)) ||
    (flyoutHoldsRail() && over(document.getElementById(BAR_SLOT_ID), x, y)));
  const core = createPeekCore({ nav, firstKey: FIRST_KEY, isPeeking: () => state === 'peek', holds: inMenu, inside, clock });
  const state = $derived<BarVisual>(barState({
    show: true,
    drawn: true,
    editing: false,
    folded: false,
    panelShown: false,
    mode: barPinned('rail') ? 'pinned' : 'autohide',
    ...core.flags,
  }));

  useStripEscape({
    open: () => !barPinned('rail') && (state === 'peek' || activeFlyout() !== null),
    hide: () => {
      closeFlyout();
      core.fold();
    },
  });

  $effect(() => {
    const slot = document.getElementById(FLYOUT_CONTAINER_ID);
    if (!slot) return;
    const enter = (event: PointerEvent): void => {
      if (flyoutHoldsRail()) core.onpointerenter(event);
    };
    const foot = document.getElementById(BAR_SLOT_ID);
    for (const el of [slot, foot]) {
      el?.addEventListener('pointerenter', enter);
      el?.addEventListener('pointerleave', core.onpointerleave);
    }
    return () => {
      for (const el of [slot, foot]) {
        el?.removeEventListener('pointerenter', enter);
        el?.removeEventListener('pointerleave', core.onpointerleave);
      }
    };
  });

  let before: BarVisual = 'handle';
  let menuWas = false;
  let activeWas: string | null = null;
  $effect(() => {
    const now = state;
    const menuNow = activeFlyout() === MENU_FLYOUT;
    const wasState = before;
    const wasMenu = menuWas;
    const wasActive = activeWas;
    activeWas = activeFlyout();
    before = now;
    menuWas = menuNow;
    if (now === 'peek' && wasState !== 'peek' && !core.flags.retracting && !barPinned('rail') && activeFlyout() !== MENU_FLYOUT && !(activeFlyout() === null && wasActive !== null)) openFlyout(MENU_FLYOUT);
    else if (now === 'handle' && wasState === 'peek' && menuNow) closeFlyout();
    else if (now === 'peek' && wasMenu && !menuNow && !core.pointerInside()) core.fold();
  });

  return {
    get state(): BarVisual {
      return state;
    },
    onpointerenter: core.onpointerenter,
    onpointerleave: core.onpointerleave,
    onfocusin: core.onfocusin,
    onfocusout: core.onfocusout,
    onkeydown: core.onkeydown,
    onpress: core.onpress,
    fold: core.fold,
  };
}
