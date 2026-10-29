/* the account chip */
import { flushSync } from 'svelte';
import { drawerEnv } from './env';
import { mountPanel, unmountPanel } from '../mount';
import { toggleAccountMenu } from '../drawer-hud/account-menu.svelte';
import { openSignInDoor } from '../carnivore-account/sign-in-door';
import { BAR_INDICATOR_ACTION, cplugBarIndicators } from '../../cplugs/host/readers';
import { BEAST_BAR_ACTION, beastIndicator } from '../beast-mode/control.svelte';
import DrawerBar from './DrawerBar.svelte';
import { barView, type VersionView } from './bar-view.svelte';


interface BarGlobals {
    VersionFooter?: {
        RELEASE_NOTES_URL: string;
        UNKNOWN_TEXT: string;
        PREVIEW_TEXT: string;
        readVersionText(): string;
        shortVersion(full: string): { text: string; preview: boolean };
    };
    CloudeWeb?: {
        layoutEditor?: LayoutEditor;
        masterAllEnabled?(): boolean;
        setMasterAll?(on: boolean): void;
        openSettingsScreen?(): boolean;
        openDocsScreen?(): boolean;
    };
}

interface LayoutEditor {
    active(): boolean;
    available(): boolean;
    toggle(): void;
}

function g(): BarGlobals {
    return drawerEnv() as BarGlobals;
}

const SLOT_ID = 'session-sidebar-bar-slot';

const LAYOUT_MIN_WIDTH = 1024;

export function layoutEntry(): { active: boolean; available: boolean } | null {
    const editor = g().CloudeWeb?.layoutEditor;
    if (!editor) return null;
    if (typeof window !== 'undefined' && window.innerWidth < LAYOUT_MIN_WIDTH) return null;
    const active = !!editor.active();
    return { active, available: active || !!editor.available() };
}


export function masterAllOn(): boolean | null {
    const web = g().CloudeWeb;
    if (!web || typeof web.masterAllEnabled !== 'function') return null;
    return !!web.masterAllEnabled();
}

export function run(action: string | null, el: Element | null): void {
    const G = g();
    if (action === `${BEAST_BAR_ACTION}${beastIndicator.id}`) {
        beastIndicator.run(el as HTMLElement | null);
        return;
    }
    if (action && action.startsWith(BAR_INDICATOR_ACTION)) {
        cplugBarIndicators().find((item) => item.action === action)?.run(el as HTMLElement | null);
        return;
    }
    if (action === 'settings') {
        G.CloudeWeb?.openSettingsScreen?.();
        return;
    }
    if (action === 'help') {
        G.CloudeWeb?.openDocsScreen?.();
        return;
    }
    if (action === 'layout') {
        const editor = G.CloudeWeb?.layoutEditor;
        if (editor) editor.toggle();
        paint();
        return;
    }
    if (action === 'account') {
        toggleAccountMenu(el as HTMLElement | null);
        return;
    }
    if (action === 'signin') {
        openSignInDoor('chip');
        return;
    }
    if (action === 'master_all') {
        const web = G.CloudeWeb;
        if (web && typeof web.setMasterAll === 'function' && typeof web.masterAllEnabled === 'function') {
            web.setMasterAll(!web.masterAllEnabled());
        }
        paint();
        return;
    }
}

let mountedIn: Element | null = null;
let wired = false;

function versionView(): VersionView | null {
    const footer = g().VersionFooter;
    if (!footer) return null;
    const resolved = footer.readVersionText();
    if (!resolved) return { text: footer.UNKNOWN_TEXT, preview: false, previewText: footer.PREVIEW_TEXT, href: null };
    const short = footer.shortVersion(resolved);
    return { text: short.text, preview: short.preview, previewText: footer.PREVIEW_TEXT, href: footer.RELEASE_NOTES_URL };
}

export function paint(): void {
    const slot = document.getElementById(SLOT_ID);
    if (!slot) return;
    if (!wired) {
        wired = true;
        slot.addEventListener('click', (e) => {
            const target = e.target as Element | null;
            const btn = target && target.closest ? target.closest('[data-bar-action]') : null;
            if (btn) run(btn.getAttribute('data-bar-action'), btn);
        });
    }
    const crown = masterAllOn() === true;
    if (barView.crown !== crown) barView.crown = crown;
    const version = versionView();
    const old = barView.version;
    if (!old || !version || old.text !== version.text || old.preview !== version.preview || old.href !== version.href) barView.version = version;
    if (mountedIn !== slot) {
        mountPanel(SLOT_ID, DrawerBar, { view: barView });
        mountedIn = slot;
    }
    flushSync();
}

export function reset(): void {
    unmountPanel(SLOT_ID);
    mountedIn = null;
    wired = false;
    barView.crown = false;
    barView.version = null;
}

if (typeof window !== 'undefined') {
    window.addEventListener('cloude:master-all', paint);
    window.addEventListener('cloude:size-master', paint);
}
