import * as host from '../../opscenter/api/host';
import { clickEnv } from '../drawer/click-env';

export const PAGE_TARGETS = {
    home: host.openHome,
    sessions: host.openSessions,
    settings: host.openSettings,
    themes: host.openThemes,
    plugins: host.openPlugins,
    widgets: host.openWidgets,
    catalog: host.openCatalog,
    blueprints: host.openBlueprints,
    ledger: host.openLedger,
    hosts: host.openHosts,
} as const;

export type PageId = keyof typeof PAGE_TARGETS;

export type NavTarget =
    | { kind: 'session'; id: string; tmuxName: string }
    | { kind: 'layout'; uuid: string }
    | { kind: 'page'; page: PageId };

async function openSessionTarget(id: string, tmuxName: string): Promise<boolean> {
    const env = clickEnv();
    if (env.SoloWindow && await env.SoloWindow.focusIfOpen(id)) return true;
    const nav = env.NavigationGeneration ? env.NavigationGeneration.begin('goto:' + id) : null;
    if (env.API && env.App) {
        const info = await env.API.getSession(id, {
            includeScrollback: true, parallelHistory: true, scrollbackLines: env.CloudeTerminal?.SCROLLBACK_ROWS,
        });
        if (env.NavigationGeneration && !env.NavigationGeneration.keep(nav, 'goto:' + id)) return false;
        if (info) {
            await env.App.returnToExistingTerminal(info);
            return true;
        }
    }
    return host.openSession(id, tmuxName);
}

function openLayoutTarget(uuid: string): boolean {
    const page = (globalThis as { CloudeWeb?: { layoutPage?: { openLayout?: (uuid: string) => unknown } } }).CloudeWeb?.layoutPage;
    if (typeof page?.openLayout === 'function') void page.openLayout(uuid);
    else globalThis.location.assign(`/layout/${encodeURIComponent(uuid)}`);
    return true;
}

export async function goTo(target: NavTarget): Promise<boolean> {
    try {
        if (target.kind === 'session') return await openSessionTarget(target.id, target.tmuxName);
        if (target.kind === 'layout') return openLayoutTarget(target.uuid);
        return PAGE_TARGETS[target.page]();
    } catch (err) {
        console.error('goTo: opening failed', target.kind, err);
        return false;
    }
}
