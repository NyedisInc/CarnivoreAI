import { flushSync } from 'svelte';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { addToMenuBridge } from '../add-to-menu/host';
import { ensurePanel } from '../mount';
import { hg } from '../sidebar-shell/interaction-globals';
import ItemMenuHost from './ItemMenuHost.svelte';
import './menus/all';
import { itemMenu } from './registry';
import type { ItemMenuContexts, ItemMenuEnv, ItemMenuType } from './types';

export interface OpenItemMenu {
    type: ItemMenuType;
    nodes: MenuNode[];
    ariaLabel: string;
    anchor: Element;
    at: { x: number; y: number } | null;
    nestedIn: HTMLElement | null;
    seq: number;
}

export interface ItemMenuOpenOptions {
    nestedIn?: HTMLElement | null;
    onClose?: () => void;
    pinnedTheme?: string | null;
}

interface OpenSource {
    type: ItemMenuType;
    ctx: unknown;
    onClose: (() => void) | null;
    releaseTheme: (() => void) | null;
}

let source: OpenSource | null = null;
let openings = 0;

export const MENU_HOST_ID = 'item-menu-host';

class ItemMenuState {
    open = $state.raw<OpenItemMenu | null>(null);
}

export const itemMenuState = new ItemMenuState();

function ensureHost(): void {
    if (document.getElementById(MENU_HOST_ID)) return;
    const host = document.createElement('div');
    host.id = MENU_HOST_ID;
    host.style.display = 'contents';
    document.body.appendChild(host);
}

function glyph(icon: string | undefined): string {
    const icons = hg().SessionRowMenuIcons;
    return icon && icons ? icons.svg(icon) : '';
}

export const ITEM_MENU_ENV: ItemMenuEnv = { close: closeItemMenu, glyph, refresh: () => refreshItemMenu() };

interface ThemeGlobals {
    Themes?: { applyScopeTo?(el: Element, ctx: { pinnedTheme: string | null }): () => void };
}

function applyTheme(host: Element, pinnedTheme: string | null | undefined): (() => void) | null {
    if (pinnedTheme === undefined) return null;
    const themes = (globalThis as unknown as ThemeGlobals).Themes;
    return themes && typeof themes.applyScopeTo === 'function' ? themes.applyScopeTo(host, { pinnedTheme }) : null;
}

function placeHost(inside: HTMLElement | null): HTMLElement {
    ensureHost();
    const host = document.getElementById(MENU_HOST_ID) as HTMLElement;
    const parent = inside ?? document.body;
    if (host.parentElement !== parent) parent.appendChild(host);
    return host;
}

export function openItemMenu<T extends ItemMenuType>(
    type: T, ctx: ItemMenuContexts[T], anchor: Element, at: { x: number; y: number } | null = null, opts: ItemMenuOpenOptions = {},
): boolean {
    const built = itemMenu(type, ctx, ITEM_MENU_ENV);
    if (!built) return false;
    closeItemMenu();
    hg().SessionSidebarGroupActions?.closeMenu?.();
    const nestedIn = opts.nestedIn ?? null;
    const host = placeHost(nestedIn);
    ensurePanel(MENU_HOST_ID, ItemMenuHost, {});
    source = { type, ctx, onClose: opts.onClose ?? null, releaseTheme: applyTheme(host, opts.pinnedTheme) };
    if (anchor.hasAttribute('aria-expanded')) anchor.setAttribute('aria-expanded', 'true');
    itemMenuState.open = { type, nodes: built.nodes, ariaLabel: built.ariaLabel, anchor, at, nestedIn, seq: ++openings };
    flushSync();
    return true;
}

export function closeItemMenu(): void {
    const was = itemMenuState.open;
    const ending = source;
    source = null;
    if (was) itemMenuState.open = null;
    if (was && was.anchor.getAttribute('aria-expanded') === 'true') was.anchor.setAttribute('aria-expanded', 'false');
    ending?.releaseTheme?.();
    ending?.onClose?.();
    addToMenuBridge.close();
}

export function refreshItemMenu(patch?: Record<string, unknown>): void {
    const open = itemMenuState.open;
    if (!open || !source) return;
    const ctx = patch ? { ...(source.ctx as Record<string, unknown>), ...patch } : source.ctx;
    const built = itemMenu(source.type, ctx as never, ITEM_MENU_ENV);
    if (!built) { closeItemMenu(); return; }
    source.ctx = ctx;
    itemMenuState.open = { ...open, nodes: built.nodes, ariaLabel: built.ariaLabel };
}

export function openItemMenuContext(): unknown {
    return itemMenuState.open && source ? source.ctx : null;
}
