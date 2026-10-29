import { clickEnv } from './click-env';
import { runWake } from './row-menu-sleep';

interface WakeRow { name?: string; asleep?: boolean; session_uuid?: string; label?: unknown }

interface WakeCtrl { _rows?: WakeRow[] }

const inflight = new Set<string>();

function liveRowElement(ctrl: WakeCtrl, sessionUuid: string): Element | null {
    const row = (ctrl._rows ?? []).find((r) => r && !r.asleep && r.session_uuid === sessionUuid);
    if (!row || typeof document === 'undefined') return null;
    const els = document.querySelectorAll<HTMLElement>('.session-sidebar-row');
    return Array.from(els).find((el) => el.dataset.sessionUuid === sessionUuid && el.dataset.asleep !== '1') ?? null;
}

export async function onAsleepClick<C extends WakeCtrl>(
    ctrl: C, rowEl: Element, open?: (ctrl: C, rowEl: Element) => Promise<unknown>,
): Promise<boolean> {
    const env = clickEnv();
    const sessionUuid = rowEl instanceof HTMLElement ? rowEl.dataset.sessionUuid ?? '' : '';
    const row = sessionUuid ? (ctrl._rows ?? []).find((r) => r && r.session_uuid === sessionUuid) ?? null : null;
    if (!row) return false;
    const name = row.name ?? '';
    if (sessionUuid && inflight.has(sessionUuid)) return true;
    const nav = env.NavigationGeneration ? env.NavigationGeneration.begin('wake:' + name) : null;
    if (sessionUuid) inflight.add(sessionUuid);
    let started = false;
    try {
        started = await runWake({
            name, label: (row.label != null && String(row.label)) || '', sessionUuid, surface: 'sidebar',
        });
    } finally {
        if (sessionUuid) inflight.delete(sessionUuid);
    }
    if (!started) return true;
    if (env.NavigationGeneration && !env.NavigationGeneration.keep(nav, 'open after wake of ' + name)) return true;
    const el = liveRowElement(ctrl, sessionUuid);
    if (el && typeof open === 'function') await open(ctrl, el);
    return true;
}
