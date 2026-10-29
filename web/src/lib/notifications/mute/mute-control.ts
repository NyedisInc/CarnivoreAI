import { t } from '../../i18n/index.svelte';
import { currentScreenFilter } from '../screen-filter';
import { setMute, type MuteScope } from './api';
import './mute.css';

export const MUTED_TOAST_KIND = 'NotifyMuted';

type ToastLike = Record<string, unknown> & { notify_type?: unknown; mute_undo?: unknown };

export interface NotifyMuteGlobal {
    attach(card: HTMLElement, toast: ToastLike | null | undefined): void;
}

interface ToastSurface {
    add(toast: Record<string, unknown>): void;
}

const SVG_NS = 'http://www.w3.org/2000/svg';

function muteGlyph(): SVGSVGElement {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 16 16');
    svg.setAttribute('width', '12');
    svg.setAttribute('height', '12');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.4');
    svg.setAttribute('stroke-linecap', 'round');
    for (const d of ['M4 11V7a4 4 0 0 1 6.5-3.1', 'M12 6.5V11H3.5', 'M6.5 13.5h3', 'M2 2l12 12']) {
        const path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute('d', d);
        svg.appendChild(path);
    }
    return svg;
}

function typeLabel(type: string): string {
    const key = currentScreenFilter()?.labelKey(type);
    return key ? t(key) : type;
}

function clear(card: HTMLElement): void {
    card.querySelectorAll(':scope > .toast__mute, :scope > .toast__mute-undo, :scope > .notify-mute-pop').forEach((n) => n.remove());
    card.classList.remove('toast--mutable');
}

function shield(el: HTMLElement): void {
    el.addEventListener('keydown', (evt) => {
        if (evt.key === 'Enter' || evt.key === ' ') evt.stopPropagation();
    });
}

function closeAll(): void {
    document.querySelectorAll('.notify-mute-pop').forEach((n) => n.remove());
}

async function mute(type: string, scope: MuteScope): Promise<void> {
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    const label = typeLabel(type);
    try {
        currentScreenFilter()?.applyMutes(await setMute(type, scope, true));
    } catch {
        surface?.add(confirmCard(t('notify.mute.failed', { type: label }), null));
        return;
    }
    const undo = async (): Promise<void> => {
        try {
            currentScreenFilter()?.applyMutes(await setMute(type, scope, false));
        } catch {
            surface?.add(confirmCard(t('notify.mute.undo_failed', { type: label }), null));
        }
    };
    const key = scope === 'here' ? 'notify.mute.toast.here' : 'notify.mute.toast.everywhere';
    surface?.add(confirmCard(t(key, { type: label }), undo));
}

function confirmCard(title: string, undo: (() => Promise<void>) | null): Record<string, unknown> {
    return {
        id: `notify-mute:${Date.now()}:${Math.random().toString(16).slice(2, 8)}`,
        session_id: null,
        kind: MUTED_TOAST_KIND,
        title,
        body: '',
        session_label: t('notify.mute.toast.surface'),
        mute_undo: undo,
        local: true,
    };
}

function openPopover(card: HTMLElement, button: HTMLButtonElement, type: string): void {
    const pop = document.createElement('div');
    pop.className = 'notify-mute-pop popup-focus';
    pop.setAttribute('role', 'menu');
    pop.setAttribute('aria-label', t('notify.mute.menu', { type: typeLabel(type) }));
    const items: Array<[MuteScope, string]> = [['here', 'notify.mute.here'], ['everywhere', 'notify.mute.everywhere']];
    for (const [scope, key] of items) {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'notify-mute-pop__item';
        item.setAttribute('role', 'menuitem');
        item.dataset.scope = scope;
        item.textContent = t(key);
        item.addEventListener('click', (evt) => {
            evt.stopPropagation();
            closeAll();
            void mute(type, scope);
        });
        shield(item);
        pop.appendChild(item);
    }
    pop.addEventListener('click', (evt) => evt.stopPropagation());
    pop.addEventListener('keydown', (evt) => {
        if (evt.key === 'Escape') {
            evt.stopPropagation();
            closeAll();
            button.focus();
        }
    });
    card.appendChild(pop);
    (pop.firstElementChild as HTMLElement | null)?.focus();
    const away = (evt: Event): void => {
        if (!pop.isConnected) return document.removeEventListener('mousedown', away, true);
        if (evt.target instanceof Node && (pop.contains(evt.target) || button.contains(evt.target))) return;
        pop.remove();
        document.removeEventListener('mousedown', away, true);
    };
    document.addEventListener('mousedown', away, true);
}

export function attach(card: HTMLElement, toast: ToastLike | null | undefined): void {
    clear(card);
    if (!toast) return;
    if (typeof toast.mute_undo === 'function') {
        const undo = toast.mute_undo as () => Promise<void>;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'toast__mute-undo';
        btn.textContent = t('notify.mute.undo');
        btn.addEventListener('click', (evt) => {
            evt.stopPropagation();
            void undo();
            (card.querySelector(':scope > .toast__dismiss') as HTMLElement | null)?.click();
        });
        shield(btn);
        card.appendChild(btn);
        card.classList.add('toast--mutable');
        return;
    }
    const filter = currentScreenFilter();
    const type = toast.notify_type;
    if (!filter || !filter.isKnown(type)) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'toast__mute';
    const label = t('notify.mute.button', { type: typeLabel(type) });
    btn.setAttribute('aria-label', label);
    btn.setAttribute('title', label);
    btn.setAttribute('aria-haspopup', 'menu');
    btn.appendChild(muteGlyph());
    btn.addEventListener('click', (evt) => {
        evt.stopPropagation();
        const open = card.querySelector(':scope > .notify-mute-pop');
        closeAll();
        if (!open) openPopover(card, btn, type);
    });
    shield(btn);
    card.appendChild(btn);
    card.classList.add('toast--mutable');
}

export function installNotifyMute(): void {
    (globalThis as unknown as { NotifyMute?: NotifyMuteGlobal }).NotifyMute = { attach };
}
