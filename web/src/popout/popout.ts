/* there is nothing */

import { readMigrating, writeMigrating } from '../lib/browser-storage-migrate';
import { BROWSER_ID } from '../lib/browser/browser-id';
import { BOARD_PARAM } from '../opscenter/engine/home-boards';
import { SIZE_UNIT_PX, suggestedSizes } from '../opscenter/widgets/fits';
import type { WidgetFits } from '../opscenter/widgets/types';
import { HEAD_ROW_PX } from '../opscenter/shell/widget-head';

export const POPOUT_PATH = '/static/popout.html';

export const WALLBOARD_PATH = `${POPOUT_PATH}?view=wallboard`;

export const WALLBOARD_WINDOW_NAME = 'carnivore-wallboard';

export const WALLBOARD_GEOMETRY_KEY = 'carnivore.popout.wallboard.geometry';

export const POPOUT_WINDOW_NAME = 'carnivore-stats';

export const POPOUT_GEOMETRY_KEY = 'carnivore.popout.home.geometry';

export const POPOUT_MIN = Object.freeze({ width: 360, height: 280 });

export const POPOUT_DEFAULT = Object.freeze({ width: 1100, height: 760 });

export const POPOUT_SAVE_DELAY_MS = 400;

export interface PopoutGeometry {
    width: number;
    height: number;
    left?: number;
    top?: number;
}

function finite(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value);
}

export function parseGeometry(raw: string | null): PopoutGeometry {
    if (!raw) return { ...POPOUT_DEFAULT };
    let value: unknown;
    try {
        value = JSON.parse(raw);
    } catch {
        return { ...POPOUT_DEFAULT };
    }
    const g = value as Partial<PopoutGeometry> | null;
    if (!g || !finite(g.width) || !finite(g.height)) return { ...POPOUT_DEFAULT };
    const out: PopoutGeometry = {
        width: Math.max(POPOUT_MIN.width, Math.round(g.width)),
        height: Math.max(POPOUT_MIN.height, Math.round(g.height)),
    };
    if (finite(g.left) && finite(g.top) && g.left > -10000 && g.top > -10000) {
        out.left = Math.round(g.left);
        out.top = Math.round(g.top);
    }
    return out;
}

export function featuresFor(g: PopoutGeometry): string {
    const parts = ['popup=yes', `width=${g.width}`, `height=${g.height}`];
    if (g.left !== undefined && g.top !== undefined) parts.push(`left=${g.left}`, `top=${g.top}`);
    return parts.join(',');
}

export function openHomePopout(win: Window = window): Window | null {
    const geometry = parseGeometry(readMigrating(POPOUT_GEOMETRY_KEY));
    const opened = win.open(POPOUT_PATH, POPOUT_WINDOW_NAME, featuresFor(geometry));
    opened?.focus();
    return opened;
}

export const DASHBOARD_EDIT_PARAM = 'edit';

export const DASHBOARD_GEOMETRY_KEY = 'carnivore.popout.dashboard.geometry';

export const DASHBOARD_LAYOUT_PARAM = 'layout';

export function openDashboardPopout(id: string, win: Window = window, editing = false): Window | null {
    const geometry = parseGeometry(readMigrating(DASHBOARD_GEOMETRY_KEY));
    const layout = editing ? `&${DASHBOARD_LAYOUT_PARAM}=1` : '';
    const path = `${POPOUT_PATH}?${BOARD_PARAM}=${encodeURIComponent(id)}&${DASHBOARD_EDIT_PARAM}=1${layout}`;
    const opened = win.open(path, `carnivore-dashboard-${id}`, featuresFor(geometry));
    opened?.focus();
    return opened;
}

export function dashboardFromSearch(search: string): string | null {
    const params = new URLSearchParams(search);
    if (params.get(DASHBOARD_EDIT_PARAM) !== '1' || params.get('view') === 'wallboard') return null;
    const id = params.get(BOARD_PARAM);
    return id && /^[A-Za-z0-9_-]{1,32}$/.test(id) ? id : null;
}

export function dashboardOpensEditing(search: string): boolean {
    return dashboardFromSearch(search) !== null && new URLSearchParams(search).get(DASHBOARD_LAYOUT_PARAM) === '1';
}

export function openWallboard(win: Window = window, board?: string): Window | null {
    const geometry = parseGeometry(readMigrating(WALLBOARD_GEOMETRY_KEY));
    const path = board ? `${WALLBOARD_PATH}&${BOARD_PARAM}=${encodeURIComponent(board)}` : WALLBOARD_PATH;
    const opened = win.open(path, WALLBOARD_WINDOW_NAME, featuresFor(geometry));
    opened?.focus();
    return opened;
}

export function rememberGeometry(
    win: Window = window,
    delayMs: number = POPOUT_SAVE_DELAY_MS,
    key: string = POPOUT_GEOMETRY_KEY,
): () => void {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const save = (): void => {
        timer = null;
        const g: PopoutGeometry = {
            width: win.outerWidth,
            height: win.outerHeight,
            left: win.screenX,
            top: win.screenY,
        };
        if (!finite(g.width) || !finite(g.height) || g.width <= 0 || g.height <= 0) return;
        writeMigrating(key, JSON.stringify(g));
    };
    const queue = (): void => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(save, delayMs);
    };
    win.addEventListener('resize', queue);
    win.addEventListener('pagehide', save);
    let lastPos = `${win.screenX},${win.screenY}`;
    const poll = win.setInterval(() => {
        const pos = `${win.screenX},${win.screenY}`;
        if (pos !== lastPos) {
            lastPos = pos;
            queue();
        }
    }, 2000);
    return () => {
        win.removeEventListener('resize', queue);
        win.removeEventListener('pagehide', save);
        win.clearInterval(poll);
        if (timer) clearTimeout(timer);
    };
}

export function focusMainWindow(win: Window = window): boolean {
    const opener = win.opener as Window | null;
    if (!opener || opener.closed) return false;
    opener.focus();
    return true;
}

export function hasMainWindow(win: Window = window): boolean {
    const opener = win.opener as Window | null;
    return !!opener && !opener.closed;
}

export const WIDGET_PARAM = 'widget';

export const WIDGET_WINDOW_CAP = Object.freeze({ width: 900, height: 700 });

const WIDGET_ID = /^(?:core\.[a-z0-9][a-z0-9-]*|[a-z][a-z0-9]{1,23}\.[a-z][a-z0-9-]{0,31}:[a-z0-9][a-z0-9:_-]{0,63})$/;

export function isWidgetId(id: unknown): id is string {
    return typeof id === 'string' && WIDGET_ID.test(id);
}

export function widgetFromSearch(search: string): string | null {
    const id = new URLSearchParams(search).get(WIDGET_PARAM);
    return isWidgetId(id) ? id : null;
}

export const PLACEMENT_PARAMS = Object.freeze({ session: 'session', view: 'view', options: 'options' });

/* session it was about */
export interface PopoutPlacement {
    sessionId?: string | null;
    view?: string | null;
    options?: Readonly<Record<string, boolean | number | string>>;
}

function isOptionValue(value: unknown): value is boolean | number | string {
    return typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string';
}

export function widgetPath(id: string, placement: PopoutPlacement = {}): string {
    const params = new URLSearchParams({ [WIDGET_PARAM]: id });
    if (placement.sessionId) params.set(PLACEMENT_PARAMS.session, placement.sessionId);
    if (placement.view) params.set(PLACEMENT_PARAMS.view, placement.view);
    if (placement.options && Object.keys(placement.options).length > 0) params.set(PLACEMENT_PARAMS.options, JSON.stringify(placement.options));
    return `${POPOUT_PATH}?${params.toString()}`;
}

export function placementFromSearch(search: string): PopoutPlacement {
    const params = new URLSearchParams(search);
    const out: PopoutPlacement = {};
    const session = params.get(PLACEMENT_PARAMS.session);
    if (session) out.sessionId = session;
    const view = params.get(PLACEMENT_PARAMS.view);
    if (view && /^[a-z][a-z0-9_-]{0,31}$/.test(view)) out.view = view;
    const raw = params.get(PLACEMENT_PARAMS.options);
    if (raw) {
        try {
            const parsed: unknown = JSON.parse(raw);
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                out.options = Object.fromEntries(Object.entries(parsed).filter(([, value]) => isOptionValue(value)));
            }
        } catch (error) {
            if (!(error instanceof SyntaxError)) throw error;
        }
    }
    return out;
}

export function widgetWindowName(id: string): string {
    return `carnivore-widget-${id}`;
}

export function widgetGeometryKey(id: string): string {
    return `carnivore.popout.widget.${id}.geometry`;
}

export const AGENT_PARAM = 'agent';

export function agentFromSearch(search: string): number | null {
    const raw = new URLSearchParams(search).get(AGENT_PARAM);
    return raw !== null && /^[1-9][0-9]{0,14}$/.test(raw) ? Number(raw) : null;
}

export function agentPath(id: number): string {
    return `${POPOUT_PATH}?${AGENT_PARAM}=${id}`;
}

export function agentWindowName(id: number): string {
    return `carnivore-agent-${id}`;
}

export function agentGeometryKey(id: number): string {
    return `carnivore.popout.agent.${id}.geometry`;
}

export function openAgentPopout(id: number, size: { width: number; height: number }, win: Window = window): Window | null {
    const saved = readMigrating(agentGeometryKey(id));
    const geometry = saved ? parseGeometry(saved) : parseGeometry(JSON.stringify(size));
    const opened = win.open(agentPath(id), agentWindowName(id), featuresFor(geometry));
    opened?.focus();
    return opened;
}

export function widgetWindowSize(fits: WidgetFits): { width: number; height: number } {
    if (fits.anySize) return { ...WIDGET_WINDOW_CAP };
    const top = suggestedSizes(fits).reduce((a, b) => (b.w * b.h > a.w * a.h ? b : a));
    return {
        width: Math.min(WIDGET_WINDOW_CAP.width, Math.max(POPOUT_MIN.width, top.w * SIZE_UNIT_PX.w)),
        height: Math.min(WIDGET_WINDOW_CAP.height, Math.max(POPOUT_MIN.height, top.h * SIZE_UNIT_PX.h + HEAD_ROW_PX)),
    };
}

export function openWidgetPopout(id: string, fits: WidgetFits, win: Window = window, placement: PopoutPlacement = {}): Window | null {
    if (!isWidgetId(id)) return null;
    const saved = readMigrating(widgetGeometryKey(id));
    const geometry = saved ? parseGeometry(saved) : widgetWindowSize(fits);
    const opened = win.open(widgetPath(id, placement), widgetWindowName(id), featuresFor(geometry));
    opened?.focus();
    return opened;
}

export const BROWSER_PARAM = 'browser';

export const BROWSER_GEOMETRY_KEY = 'carnivore.popout.browser.geometry';

export function browserFromSearch(search: string): string | null {
    const id = new URLSearchParams(search).get(BROWSER_PARAM);
    return id !== null && BROWSER_ID.test(id) ? id : null;
}

export function browserPath(id: string): string {
    return `${POPOUT_PATH}?${BROWSER_PARAM}=${encodeURIComponent(id)}`;
}

export function browserWindowName(id: string): string {
    return `carnivore-browser-${id}`;
}
