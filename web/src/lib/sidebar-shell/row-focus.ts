import { drawer, listElement, rg } from './row-globals';
import { isBandOrderKey } from '../drawer/store-keys';

const stop: { name: string | null; band: string | null } = { name: null, band: null };

export function rowEls(): HTMLElement[] {
    const list = listElement();
    return list ? Array.from(list.querySelectorAll<HTMLElement>('.session-sidebar-row')) : [];
}

export function visibleNames(): string[] {
    return rowEls().map((el) => el.dataset.name || '').filter((n) => !!n);
}

export function bandNames(band: string): string[] {
    return rowEls().filter((el) => el.dataset.band === band)
        .map((el) => el.dataset.name || '').filter((n) => !!n);
}

export function ownsOrder(band: string | null | undefined): boolean {
    return !!band && isBandOrderKey(band);
}

function pick(rows: HTMLElement[], name: string | null, band: string | null): HTMLElement | null {
    let byName: HTMLElement | null = null;
    for (const el of rows) {
        if (el.dataset.name !== name) continue;
        if (band != null && el.dataset.band === band) return el;
        if (!byName) byName = el;
    }
    return byName || rows[0] || null;
}

export function setFocusRow(name: string | null, band: string | null | undefined, takeFocus: boolean): void {
    const rows = rowEls();
    const target = pick(rows, name, band ?? null);
    if (!target) return;
    for (const el of rows) {
        const want = el === target ? '0' : '-1';
        if (el.getAttribute('tabindex') !== want) el.setAttribute('tabindex', want);
    }
    stop.name = target.dataset.name || null;
    stop.band = target.dataset.band || null;
    if (takeFocus && document.activeElement !== target) target.focus();
}

export function afterRender(): void {
    const list = listElement();
    if (!list) return;
    setFocusRow(stop.name, stop.band, document.activeElement === list);
}

export function repaintKeepingFocus(name: string, band?: string | null): void {
    stop.name = name;
    stop.band = band || null;
    const ctrl = drawer();
    if (ctrl && typeof ctrl.repaint === 'function') ctrl.repaint();
    setFocusRow(name, stop.band, true);
}

export function focusStop(): { name: string | null; band: string | null } {
    return { ...stop };
}
