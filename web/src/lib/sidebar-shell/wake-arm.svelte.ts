export const ARM_GRACE_MS = 300;

export const wakeArm = $state<{ key: string; name: string; band: string; busy: boolean; armedAt: number }>({
    key: '', name: '', band: '', busy: false, armedAt: 0,
});

let listening = false;
const armableRows = new WeakSet<Element>();
let panelWatch: MutationObserver | null = null;

export function wakeArmable(led: { status: string | null } | null | undefined, ghost: unknown): boolean {
    return !!led && led.status === 'asleep' && !ghost;
}

export function markArmable(armable: boolean): (el: Element) => (() => void) | void {
    return (el) => {
        if (!armable) return;
        armableRows.add(el);
        return () => { armableRows.delete(el); };
    };
}

export function isArmableRow(el: Element): boolean {
    return armableRows.has(el);
}

export function wakeArmKey(name: string, band: string | null | undefined): string {
    return `${name}|${band || ''}`;
}

export function isWakeArmed(name: string, band: string | null | undefined): boolean {
    return wakeArm.key !== '' && wakeArm.key === wakeArmKey(name, band);
}

function armedRowEl(): HTMLElement | null {
    return document.querySelector<HTMLElement>('.session-sidebar-row[data-wake-armed]');
}

function rowElFor(name: string, band: string): HTMLElement | null {
    const bandSel = band ? `[data-band="${CSS.escape(band)}"]` : ':not([data-band])';
    return document.querySelector<HTMLElement>(`.session-sidebar-row[data-name="${CSS.escape(name)}"]${bandSel}`);
}

export function refocusRow(name: string, band: string): void {
    const row = rowElFor(name, band);
    const active = document.activeElement;
    if (!row || (active && active !== document.body && !row.contains(active))) return;
    row.focus({ preventScroll: true });
}

function onKeydown(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    if (!armedRowEl()) {
        removeListeners();
        return;
    }
    if (wakeArm.busy) return;
    e.preventDefault();
    e.stopPropagation();
    const { name, band } = wakeArm;
    disarmWake();
    refocusRow(name, band);
}

function onPointerDown(e: PointerEvent): void {
    const row = armedRowEl();
    if (!row) {
        removeListeners();
        return;
    }
    if (wakeArm.busy || row.contains(e.target as Node | null)) return;
    disarmWake();
}

function addListeners(): void {
    if (listening) return;
    listening = true;
    document.addEventListener('keydown', onKeydown, true);
    document.addEventListener('pointerdown', onPointerDown, true);
}

function removeListeners(): void {
    document.removeEventListener('keydown', onKeydown, true);
    document.removeEventListener('pointerdown', onPointerDown, true);
    listening = false;
    panelWatch?.disconnect();
    panelWatch = null;
}

function watchPanel(panel: Element): void {
    panelWatch?.disconnect();
    panelWatch = new MutationObserver(() => {
        if (panel.classList.contains('session-sidebar-panel--open')
            || document.body.classList.contains('session-sidebar-pinned')) return;
        disarmWake();
    });
    panelWatch.observe(panel, { attributes: true, attributeFilter: ['class'] });
}

export function armWake(name: string, band: string | null | undefined, panel: Element | null = null): boolean {
    if (wakeArm.busy) return false;
    wakeArm.key = wakeArmKey(name, band);
    wakeArm.name = name;
    wakeArm.band = band || '';
    wakeArm.armedAt = Date.now();
    addListeners();
    if (panel) watchPanel(panel);
    return true;
}

export function disarmWake(): void {
    if (wakeArm.busy) return;
    wakeArm.key = '';
    wakeArm.name = '';
    wakeArm.band = '';
    removeListeners();
}

export function resetWakeArm(): void {
    wakeArm.busy = false;
    disarmWake();
}
