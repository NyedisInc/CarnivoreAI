/* could not the page terminal */

export const WIDTH_KEY = 'carnivore.rightDrawer.width';

export const DEFAULT_WIDTH = 320;

export const MIN_WIDTH = 220;

export const MAX_WIDTH = 720;

export const MAX_SHARE = 0.6;

export const KEY_STEP = 16;

export const MOBILE_MAX_PX = 700;

export const BODY_CLASS = 'right-drawer-docked';

export const WIDTH_VAR = '--right-dock-w';

export type DrawerKind = 'files' | 'notes';

export interface DrawerOccupant {
    root: HTMLElement;
    box: HTMLElement;
    close: () => void;
    onDockChange?: (docked: boolean) => void;
}

const occupants = new Map<DrawerKind, DrawerOccupant>();

const openers = new Map<DrawerKind, () => void>();

export const rightDrawer = $state<{ kind: DrawerKind | null; last: DrawerKind | null; width: number; docked: boolean }>({
    kind: null,
    last: null,
    width: DEFAULT_WIDTH,
    docked: false,
});

let lastPushed = '';
let watching = false;

/*  hidden  */
export function clampWidth(px: number, viewport: number): number {
    const share = viewport > 0 ? Math.floor(viewport * MAX_SHARE) : MAX_WIDTH;
    const cap = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, share));
    const wanted = Number.isFinite(px) ? px : DEFAULT_WIDTH;
    return Math.round(Math.min(Math.max(wanted, MIN_WIDTH), cap));
}

function win(): (Window & typeof globalThis) | null {
    return typeof window === 'undefined' ? null : window;
}

function viewport(): number {
    return win()?.innerWidth ?? 0;
}

export function readWidth(): number {
    let raw: string | null = null;
    try {
        raw = win()?.localStorage?.getItem(WIDTH_KEY) ?? null;
    } catch {
        raw = null;
    }
    const parsed = raw === null ? NaN : Number(raw);
    return clampWidth(Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_WIDTH, viewport());
}

function writeWidth(px: number): void {
    try {
        win()?.localStorage?.setItem(WIDTH_KEY, String(px));
    } catch {
    }
}

export function isMobile(): boolean {
    const width = viewport();
    return width > 0 && width <= MOBILE_MAX_PX;
}

/* the page terminal */
export function applyDock(refit = true): void {
    const w = win();
    const doc = w?.document;
    if (!doc) return;
    const docked = rightDrawer.kind !== null && !isMobile();
    const wasDocked = rightDrawer.docked;
    rightDrawer.docked = docked;
    rightDrawer.width = clampWidth(rightDrawer.width, viewport());
    doc.body?.classList.toggle(BODY_CLASS, docked);
    doc.documentElement?.style.setProperty(WIDTH_VAR, `${rightDrawer.width}px`);
    if (rightDrawer.kind && wasDocked !== docked) occupants.get(rightDrawer.kind)?.onDockChange?.(docked);
    const pushed = docked ? `d${rightDrawer.width}` : 'o';
    if (refit && pushed !== lastPushed) {
        lastPushed = pushed;
        const layout = (w as unknown as { TerminalLayout?: { requestFit?: (why: string) => void } }).TerminalLayout;
        layout?.requestFit?.('right-drawer');
    }
}

/* the page terminal */
export function setDrawerWidth(px: number, persist = true, refit = true): number {
    rightDrawer.width = clampWidth(px, viewport());
    if (persist) writeWidth(rightDrawer.width);
    applyDock(refit);
    return rightDrawer.width;
}

export function installGrip(box: HTMLElement): HTMLElement {
    const doc = box.ownerDocument;
    const existing = box.querySelector<HTMLElement>(':scope > .right-drawer-grip');
    if (existing) return existing;
    const grip = doc.createElement('div');
    grip.className = 'right-drawer-grip';
    grip.setAttribute('role', 'separator');
    grip.setAttribute('aria-orientation', 'vertical');
    grip.setAttribute('aria-label', 'resize drawer');
    grip.setAttribute('aria-valuemin', String(MIN_WIDTH));
    grip.setAttribute('aria-valuemax', String(MAX_WIDTH));
    grip.tabIndex = 0;
    const paint = (): void => grip.setAttribute('aria-valuenow', String(rightDrawer.width));
    paint();
    let dragging = false;
    grip.addEventListener('pointerdown', (event: PointerEvent) => {
        if (event.button !== 0) return;
        dragging = true;
        event.preventDefault();
        try { grip.setPointerCapture(event.pointerId); } catch {  }
        doc.body?.classList.add('right-drawer-resizing');
    });
    grip.addEventListener('pointermove', (event: PointerEvent) => {
        if (!dragging) return;
        setDrawerWidth(viewport() - event.clientX, false, false);
        paint();
    });
    const end = (): void => {
        if (!dragging) return;
        dragging = false;
        doc.body?.classList.remove('right-drawer-resizing');
        setDrawerWidth(rightDrawer.width, true);
        paint();
    };
    grip.addEventListener('pointerup', end);
    grip.addEventListener('pointercancel', end);
    grip.addEventListener('keydown', (event: KeyboardEvent) => {
        const step: Record<string, number> = {
            ArrowLeft: rightDrawer.width + KEY_STEP,
            ArrowRight: rightDrawer.width - KEY_STEP,
            Home: MIN_WIDTH,
            End: MAX_WIDTH,
        };
        const next = step[event.key];
        if (next === undefined) return;
        event.preventDefault();
        setDrawerWidth(next, true);
        paint();
    });
    box.prepend(grip);
    return grip;
}

export function registerOccupant(kind: DrawerKind, occupant: DrawerOccupant): void {
    occupants.set(kind, occupant);
}

export function openDrawer(kind: DrawerKind): boolean {
    watch();
    const previous = rightDrawer.kind;
    if (previous && previous !== kind) occupants.get(previous)?.close();
    const occupant = occupants.get(kind);
    if (occupant) {
        occupant.root.classList.add('right-drawer');
        occupant.root.setAttribute('data-right-drawer', kind);
        installGrip(occupant.box);
    }
    rightDrawer.kind = kind;
    rightDrawer.last = kind;
    rightDrawer.width = readWidth();
    applyDock();
    return rightDrawer.docked;
}

export function closeDrawer(kind: DrawerKind): void {
    if (rightDrawer.kind !== kind) return;
    rightDrawer.kind = null;
    applyDock();
}

export function dismissDrawer(kind: DrawerKind): boolean {
    if (rightDrawer.kind !== kind) return false;
    occupants.get(kind)?.close();
    return true;
}

export function registerOpener(kind: DrawerKind, open: () => void): void {
    openers.set(kind, open);
}

export function selectDrawer(kind: DrawerKind): boolean {
    if (rightDrawer.kind !== kind) openers.get(kind)?.();
    return rightDrawer.kind === kind;
}

export function drawerHolds(kind: DrawerKind): boolean {
    return rightDrawer.kind === kind;
}

export function drawerDocked(): boolean {
    return rightDrawer.docked;
}

function watch(): void {
    if (watching) return;
    const w = win();
    if (!w || typeof w.addEventListener !== 'function') return;
    watching = true;
    w.addEventListener('resize', () => applyDock());
}

export function resetRightDrawerForTest(): void {
    occupants.clear();
    openers.clear();
    rightDrawer.kind = null;
    rightDrawer.last = null;
    rightDrawer.width = DEFAULT_WIDTH;
    rightDrawer.docked = false;
    lastPushed = '';
}
