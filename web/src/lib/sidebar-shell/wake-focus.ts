import { activateRow, wokenRowElement } from './row-activate';
import { rg, type NavToken } from './row-globals';

export type WakeFocusOutcome = 'layout' | 'opened' | 'cancelled' | 'timeout';

export interface WakeFocusHost {
    keep(nav: NavToken): boolean;
    isLive(sessionUuid: string): boolean;
    inShowingLayout(): boolean;
    focusMember(sessionUuid: string): boolean;
    openRow(sessionUuid: string): Promise<void>;
    sleep(ms: number): Promise<void>;
}

const POLL_MS = 250;
const MAX_POLLS = 60;
const DESKTOP_MIN = 1024;

export async function afterWake(sessionUuid: string, nav: NavToken, host: WakeFocusHost): Promise<WakeFocusOutcome> {
    for (let i = 0; !host.isLive(sessionUuid); i++) {
        if (!host.keep(nav)) return 'cancelled';
        if (i >= MAX_POLLS) return 'timeout';
        await host.sleep(POLL_MS);
    }
    if (!host.keep(nav)) return 'cancelled';
    if (host.inShowingLayout() && host.focusMember(sessionUuid)) return 'layout';
    await host.openRow(sessionUuid);
    return 'opened';
}

export function browserHost(): WakeFocusHost {
    const g = rg();
    const page = () => g.CloudeWeb?.layoutPage;
    return {
        keep: (nav) => !g.NavigationGeneration || g.NavigationGeneration.keep(nav, 'focus after wake'),
        isLive: (uuid) => !!g.SessionSidebar?._rows?.some((r) => r && !r.asleep && r.session_uuid === uuid),
        inShowingLayout: () => window.innerWidth >= DESKTOP_MIN && page()?.isActive?.() === true,
        focusMember: (uuid) => page()?.focusMember?.(uuid, true) === true,
        openRow: async (uuid) => {
            const ctrl = g.SessionSidebar;
            const el = ctrl ? wokenRowElement(ctrl, uuid) : null;
            if (ctrl && el) await activateRow(ctrl, el);
        },
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    };
}

export const WakeFocus = {
    afterWake: (sessionUuid: string, nav: NavToken): Promise<WakeFocusOutcome> => afterWake(sessionUuid, nav, browserHost()),
};
