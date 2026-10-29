/*  hidden  */

const ACTIVE_CLASS = 'active';

let parked: string[] = [];

const TERMINAL_SCREEN_ID = 'terminal-screen';

/* the bottom bar */
const MAIN_SECTION_ID = 'terminal-grid';

export const MAIN_SECTION_PAGE_ATTR = 'data-center-page';

let raisedTerminalScreen = false;

interface AppLike {
    hideAllScreens?: () => void;
}

interface HeaderCalls {
    setHeaderIdentity?: (opts: { icon: string; title: string }) => void;
    setPageTitle?: (session: string | null) => void;
}

interface HeaderSnapshot {
    icon: 'cloude' | 'brand';
    title: string;
    documentTitle: string;
}

const TITLE_SUFFIX = ' - Carnivore';

let headerBefore: HeaderSnapshot | null = null;

export function parkCenterScreens(
    doc: Document = document,
    app: AppLike | undefined = (globalThis as { App?: AppLike }).App,
): void {
    const active = Array.from(doc.querySelectorAll<HTMLElement>(`.screen.${ACTIVE_CLASS}`))
        .map((el) => el.id)
        .filter((id) => id !== '');
    app?.hideAllScreens?.();
    parked = active;
}

export function occupyMainSection(doc: Document = document): void {
    const screen = doc.getElementById(TERMINAL_SCREEN_ID);
    if (screen && !screen.classList.contains(ACTIVE_CLASS)) {
        screen.classList.add(ACTIVE_CLASS);
        raisedTerminalScreen = true;
    }
    doc.getElementById(MAIN_SECTION_ID)?.setAttribute(MAIN_SECTION_PAGE_ATTR, '');
}

export function vacateMainSection(doc: Document = document): void {
    doc.getElementById(MAIN_SECTION_ID)?.removeAttribute(MAIN_SECTION_PAGE_ATTR);
    if (raisedTerminalScreen) doc.getElementById(TERMINAL_SCREEN_ID)?.classList.remove(ACTIVE_CLASS);
    raisedTerminalScreen = false;
}

function headerCalls(): HeaderCalls {
    return globalThis as unknown as HeaderCalls;
}

function readHeader(doc: Document): HeaderSnapshot {
    const text = doc.getElementById('header-title-text');
    return {
        icon: doc.getElementById('header-rename-pencil') ? 'cloude' : 'brand',
        title: text?.dataset.fullTitle ?? text?.textContent ?? '',
        documentTitle: doc.title,
    };
}

export function setBrowserHeader(title: string, doc: Document = document): void {
    if (headerBefore === null) headerBefore = readHeader(doc);
    const shown = title.trim();
    headerCalls().setHeaderIdentity?.({ icon: 'brand', title: shown });
    headerCalls().setPageTitle?.(shown === '' ? null : shown);
}

function restoreHeader(doc: Document): void {
    const before = headerBefore;
    headerBefore = null;
    if (before === null) return;
    headerCalls().setHeaderIdentity?.({ icon: before.icon, title: before.title });
    const tab = before.documentTitle.endsWith(TITLE_SUFFIX)
        ? before.documentTitle.slice(0, -TITLE_SUFFIX.length)
        : null;
    headerCalls().setPageTitle?.(tab);
}

export function dropParkedScreens(doc: Document = document): void {
    parked = [];
    headerBefore = null;
    doc.getElementById(MAIN_SECTION_ID)?.removeAttribute(MAIN_SECTION_PAGE_ATTR);
    raisedTerminalScreen = false;
}

export function restoreParkedScreens(doc: Document = document): void {
    vacateMainSection(doc);
    for (const id of parked) doc.getElementById(id)?.classList.add(ACTIVE_CLASS);
    parked = [];
    restoreHeader(doc);
}
