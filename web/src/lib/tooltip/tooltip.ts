
import { revealCutOffText } from './cut-off-reveal';

export const SHOW_DELAY_MS = 750;
export const PARK_ATTR = 'data-tooltip-title';
const EXPANDED_OK_ATTR = 'data-tooltip-expanded';
const OFF_ATTR = 'data-tooltip-off';
const SIDE_ATTR = 'data-tooltip-side';
const GAP_PX = 6;
const EDGE_PX = 8;
const BUBBLE_ID = 'cc-tooltip';

type Side = 'top' | 'bottom' | 'left' | 'right';
type Source = 'pointer' | 'focus' | 'touch';

const OPPOSITE: Record<Side, Side> = { top: 'bottom', bottom: 'top', left: 'right', right: 'left' };

let bubble: HTMLDivElement | null = null;
let raised = false;
let shown: Element | null = null;
let shownSource: Source | null = null;
let pending: Element | null = null;
let pendingSource: Source | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let dismissed: Element | null = null;
let describedByAdded = false;
const parked = new Set<Element>();
let watcher: MutationObserver | null = null;

/* title="pin to top" */
function textOf(el: Element): string {
    const own = el.getAttribute('data-tooltip');
    if (own !== null) return own.trim();
    return (el.getAttribute('title') ?? el.getAttribute(PARK_ATTR) ?? '').trim();
}

function isCarrier(el: Element): boolean {
    return el.hasAttribute('data-tooltip') || el.hasAttribute('title') || el.hasAttribute(PARK_ATTR);
}

const GENERIC_VERB = /^(?:open|close|show|hide|fold|unfold|toggle|go to|pop out)\s+/i;

function squash(s: string): string {
    return s.replace(/\s+/g, ' ').trim().toLowerCase();
}

const SHOWS_SPILL = new Set(['', 'visible']);

/* -webkit-line-clamp:2 overflow:hidden */
function cutsOff(n: HTMLElement): boolean {
    if (n.scrollWidth > n.clientWidth) return true;
    return n.scrollHeight > n.clientHeight && !SHOWS_SPILL.has(getComputedStyle(n).overflowY);
}

/*  hidden  */
function isClipped(el: Element): boolean {
    for (const n of [el, ...el.querySelectorAll('*')]) {
        if (n instanceof HTMLElement && cutsOff(n)) return true;
    }
    return false;
}

/* <button> */
function repeatsVisibleText(el: Element, words: string): boolean {
    const shown = squash(el.textContent ?? '');
    if (!shown) return false;
    const whole = squash(words);
    const rest = squash(words.replace(GENERIC_VERB, ''));
    if (!shown.includes(whole) && !(rest && shown.includes(rest))) return false;
    return !isClipped(el);
}

export function tooltipTargetFor(node: EventTarget | null): Element | null {
    for (let el = node instanceof Element ? node : null; el; el = el.parentElement) {
        if (!isCarrier(el)) continue;
        const words = textOf(el);
        if (!words) return null;
        if (repeatsVisibleText(el, words)) return null;
        if (el.closest(`[${OFF_ATTR}]`)) return null;
        if (el.getAttribute('aria-expanded') === 'true' && !el.hasAttribute(EXPANDED_OK_ATTR)) return null;
        return el;
    }
    return null;
}

function park(el: Element): void {
    const value = el.getAttribute('title');
    if (value === null) return;
    el.setAttribute(PARK_ATTR, value);
    el.removeAttribute('title');
    parked.add(el);
}

function unpark(el: Element): void {
    parked.delete(el);
    const value = el.getAttribute(PARK_ATTR);
    el.removeAttribute(PARK_ATTR);
    if (value !== null && !el.hasAttribute('title')) el.setAttribute('title', value);
}

function parkChain(node: Element | null): void {
    for (const el of [...parked]) if (!node || !el.contains(node)) unpark(el);
    for (let el = node; el; el = el.parentElement) if (el.hasAttribute('title')) park(el);
    rewatch();
}

function rewatch(): void {
    if (typeof MutationObserver !== 'function') return;
    if (!watcher) watcher = new MutationObserver(onAttributeChange);
    onAttributeChange(watcher.takeRecords());
    watcher.disconnect();
    const watched = new Set<Element>(parked);
    if (shown) watched.add(shown);
    for (const el of watched) {
        watcher.observe(el, { attributes: true, attributeFilter: ['title', 'data-tooltip'] });
    }
}

function onAttributeChange(records: MutationRecord[]): void {
    let refresh = false;
    for (const r of records) {
        const el = r.target as Element;
        if (parked.has(el) && el.hasAttribute('title')) park(el);
        if (el === shown) refresh = true;
    }
    if (!refresh || !shown) return;
    const text = textOf(shown);
    if (!text) {
        hide();
        return;
    }
    if (bubble && bubble.textContent !== text) {
        bubble.textContent = text;
        place(shown);
    }
}

function ensureBubble(): HTMLDivElement {
    if (bubble && bubble.isConnected) return bubble;
    const el = bubble ?? document.createElement('div');
    el.id = BUBBLE_ID;
    el.className = 'cc-tooltip';
    el.setAttribute('role', 'tooltip');
    el.hidden = true;
    document.body.appendChild(el);
    bubble = el;
    return el;
}

function raiseBubble(el: HTMLElement): void {
    if (typeof el.showPopover !== 'function') return;
    el.setAttribute('popover', 'manual');
    try {
        if (raised) el.hidePopover();
        el.showPopover();
        raised = true;
    } catch (err) {
        console.error('[tooltip] could not raise the bubble into the top layer:', err);
    }
}

function sideSource(target: Element): Element | null {
    const sider = target.closest(`[${SIDE_ATTR}]`);
    if (!sider) return null;
    const popup = target.closest('[role="menu"], [role="dialog"]');
    return popup && popup !== sider && sider.contains(popup) ? null : sider;
}

function place(target: Element): void {
    const el = ensureBubble();
    const r = target.getBoundingClientRect();
    const edge = (sideSource(target) ?? target).getBoundingClientRect();
    el.style.left = '0px';
    el.style.top = '0px';
    const bw = el.offsetWidth;
    const bh = el.offsetHeight;
    const vw = document.documentElement.clientWidth || window.innerWidth;
    const vh = document.documentElement.clientHeight || window.innerHeight;
    const fits: Record<Side, boolean> = {
        top: edge.top - GAP_PX - bh >= EDGE_PX,
        bottom: edge.bottom + GAP_PX + bh <= vh - EDGE_PX,
        left: edge.left - GAP_PX - bw >= EDGE_PX,
        right: edge.right + GAP_PX + bw <= vw - EDGE_PX,
    };
    const asked = sideSource(target)?.getAttribute(SIDE_ATTR) as Side | undefined;
    const want: Side = asked && asked in OPPOSITE ? asked : 'top';
    const side = fits[want] || !fits[OPPOSITE[want]] ? want : OPPOSITE[want];
    let left: number;
    let top: number;
    if (side === 'top' || side === 'bottom') {
        left = r.left + r.width / 2 - bw / 2;
        top = side === 'top' ? edge.top - GAP_PX - bh : edge.bottom + GAP_PX;
    } else {
        top = r.top + r.height / 2 - bh / 2;
        left = side === 'left' ? edge.left - GAP_PX - bw : edge.right + GAP_PX;
    }
    left = Math.max(EDGE_PX, Math.min(left, vw - bw - EDGE_PX));
    top = Math.max(EDGE_PX, Math.min(top, vh - bh - EDGE_PX));
    el.style.left = `${Math.round(left)}px`;
    el.style.top = `${Math.round(top)}px`;
    el.dataset.side = side;
    const along = side === 'top' || side === 'bottom'
        ? r.left + r.width / 2 - left
        : r.top + r.height / 2 - top;
    const span = side === 'top' || side === 'bottom' ? bw : bh;
    el.style.setProperty('--cc-arrow', `${Math.round(Math.max(8, Math.min(along, span - 8)))}px`);
}

function show(target: Element, source: Source): void {
    const text = textOf(target);
    if (!text || !target.isConnected) return;
    const el = ensureBubble();
    el.textContent = text;
    el.hidden = false;
    raiseBubble(el);
    place(target);
    shown = target;
    shownSource = source;
    const ids = (target.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
    describedByAdded = !ids.includes(BUBBLE_ID);
    if (describedByAdded) target.setAttribute('aria-describedby', [...ids, BUBBLE_ID].join(' '));
    rewatch();
}

function hide(): void {
    if (timer) clearTimeout(timer);
    timer = null;
    pending = null;
    pendingSource = null;
    if (shown && describedByAdded) {
        const ids = (shown.getAttribute('aria-describedby') ?? '').split(/\s+/).filter((id) => id && id !== BUBBLE_ID);
        if (ids.length) shown.setAttribute('aria-describedby', ids.join(' '));
        else shown.removeAttribute('aria-describedby');
    }
    shown = null;
    shownSource = null;
    describedByAdded = false;
    if (bubble) {
        bubble.hidden = true;
        if (raised && typeof bubble.hidePopover === 'function') bubble.hidePopover();
        raised = false;
    }
}

/* something else */
function schedule(target: Element, source: Source): void {
    hide();
    pending = target;
    pendingSource = source;
    timer = setTimeout(() => {
        timer = null;
        const t = pending;
        const s = pendingSource ?? source;
        pending = null;
        pendingSource = null;
        if (t) show(t, s);
    }, SHOW_DELAY_MS);
}

function onPointerOver(e: PointerEvent): void {
    if (e.pointerType === 'touch') return;
    const node = e.target instanceof Element ? e.target : null;
    parkChain(node);
    revealCutOffText(node);
    const target = tooltipTargetFor(node);
    if (target !== dismissed) dismissed = null;
    if (!target || target === dismissed) {
        if (shown || pending) hide();
        return;
    }
    if (target === shown || target === pending) return;
    if (shown && !shown.isConnected && bubble && textOf(target) === bubble.textContent) {
        const source = shownSource ?? 'pointer';
        hide();
        show(target, source);
        return;
    }
    schedule(target, 'pointer');
}

function onTouchTap(e: PointerEvent): void {
    if (e.pointerType !== 'touch') return;
    const item = e.target instanceof Element ? e.target.closest('[role^="menuitem"][aria-disabled="true"]') : null;
    const target = item ? tooltipTargetFor(item) : null;
    if (!target) {
        if (shownSource === 'touch') hide();
        return;
    }
    hide();
    show(target, 'touch');
}

function onPointerOut(e: PointerEvent): void {
    if (e.relatedTarget !== null) return;
    parkChain(null);
    dismissed = null;
    if (shown || pending) hide();
}

function onPointerDown(e: PointerEvent): void {
    dismissed = tooltipTargetFor(e.target);
    if (shown || pending) hide();
}

function onFocusIn(e: FocusEvent): void {
    const node = e.target instanceof Element ? e.target : null;
    if (!node) return;
    try {
        if (!node.matches(':focus-visible')) return;
    } catch {
    }
    const target = tooltipTargetFor(node);
    if (!target || target === shown || target === pending) return;
    schedule(target, 'focus');
}

function onFocusOut(): void {
    if (shownSource === 'focus' || pendingSource === 'focus') hide();
}

function onKeyDown(e: KeyboardEvent): void {
    if (e.key !== 'Escape' || (!shown && !pending)) return;
    dismissed = shown ?? pending;
    hide();
}

function onScroll(e: Event): void {
    const t = shown ?? pending;
    if (!t) return;
    const src = e.target;
    if (src === document || (src instanceof Node && src.contains(t))) hide();
}

function onWindowAway(): void {
    if (shown || pending) hide();
}

let installed = false;

export function installSharedTooltip(): void {
    if (installed || typeof document === 'undefined') return;
    installed = true;
    document.addEventListener('pointerover', onPointerOver, { passive: true });
    document.addEventListener('pointerout', onPointerOut, { passive: true });
    document.addEventListener('pointerdown', onPointerDown, { capture: true, passive: true });
    document.addEventListener('pointerup', onTouchTap, { passive: true });
    document.addEventListener('focusin', onFocusIn);
    document.addEventListener('focusout', onFocusOut);
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('scroll', onScroll, { capture: true, passive: true });
    window.addEventListener('blur', onWindowAway);
    document.addEventListener('visibilitychange', onWindowAway);
}
