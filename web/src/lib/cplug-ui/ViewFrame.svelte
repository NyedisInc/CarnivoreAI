
<script lang="ts">
    import { flushSync, onMount, untrack } from 'svelte';
    import { clock, startClock } from '../../opscenter/lib/frozen-clock.svelte';
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from '../plugins-page/cplugs-adapter';
    import { callViewRoute, callViewTool, fetchViewTicket } from './api';
    import { createBridge, newNonce, type ViewRole } from './bridge';
    import { readTheme, watchTheme, type ThemeValues } from './frame-theme';
    import { keepFocusOut } from './focus-return';
    import { clipPath, createTerminalWatch, enabledRects, type Rect } from './hit-regions';
    import HostFrame from './HostFrame.svelte';
    import { frameTopics, type FrameTopicHandle } from './frame-topics';
    import { shareRelay } from './share-relay';
    import { createTrailingLimiter } from './trailing-limiter';
    import { ACTIONS_WINDOW_MS, MAX_ACTION_LISTS, type ViewAction } from './view-actions';
    import { widgetMenuGesture, type OpenWidgetMenu } from '../item-menu/widget-gesture';

    interface Props {
        plugin: Pick<CplugItem, 'cplugId' | 'name' | 'unverified' | 'declared' | 'installKey'>;
        view: string;
        surface: 'panel' | 'overlay';
        viewRole?: ViewRole;
        onShow?: () => void;
        visible?: boolean;
        bar?: boolean;
        fill?: boolean;
        onActions?: (actions: ViewAction[]) => void;
        onMenu?: OpenWidgetMenu;
        themeValues?: ThemeValues;
        viewSrc?: string | null;
        t: Translate;
    }

    const { plugin, view, surface, viewRole, onShow, visible = true, bar = true, fill = false, onActions, onMenu, themeValues, viewSrc, t }: Props = $props();
    const role = $derived<ViewRole>(viewRole ?? surface);
    const declared = $derived(plugin.declared ?? { routes: [], tools: [] });
    let nonce = newNonce();
    let src = $state<string | null>(null);
    let failed = $state(false);
    let viewState = $state('');
    let declaredRects = $state<Rect[]>([]);
    let layoutTick = $state(0);
    let frameEl = $state<HTMLIFrameElement | null>(null);
    let armed = $state(false);

    function arm(focusFrame = true): void {
        if (!armed) {
            armed = true;
            flushSync();
        }
        if (focusFrame) frameEl?.focus();
    }

    function terminalRects(): Rect[] {
        return Array.from(document.querySelectorAll('.xterm')).map((el) => {
            const r = el.getBoundingClientRect();
            return { x: r.left, y: r.top, w: r.width, h: r.height };
        });
    }

    const clip = $derived.by(() => {
        void layoutTick;
        return surface === 'overlay' ? clipPath(enabledRects(declaredRects, terminalRects())) : '';
    });

    let topicHandle: FrameTopicHandle | null = null;

    const MENU_GAP_MS = 500;
    let lastMenuAt = -Infinity;
    let latestActions: ViewAction[] = [];
    const actionLimiter = createTrailingLimiter(MAX_ACTION_LISTS, ACTIONS_WINDOW_MS);

    function takeActions(list: ViewAction[]): { ok: true } | { ok: false; error: string } {
        if (!onActions || surface !== 'panel') return { ok: false, error: 'unavailable' };
        latestActions = list;
        actionLimiter.hit(() => onActions(latestActions));
        return { ok: true };
    }

    function takeMenu(at: { x: number; y: number } | null): void {
        if (!onMenu || surface !== 'panel' || !frameEl || !armed || document.activeElement !== frameEl) return;
        const now = Date.now();
        if (now - lastMenuAt < MENU_GAP_MS) return;
        lastMenuAt = now;
        const box = frameEl.getBoundingClientRect();
        onMenu(at ? { x: box.left + Math.min(Math.max(at.x, 0), box.width), y: box.top + Math.min(Math.max(at.y, 0), box.height) } : null, frameEl);
    }

    export function sendAction(id: string, on?: boolean): void {
        bridge.send('action', on === undefined ? { id } : { id, on });
    }

    function canSee(): boolean {
        return visible && !document.hidden;
    }

    function makeBridge(activeNonce: string) {
        return createBridge({
            nonce: activeNonce,
            get role() { return role; },
            get label() { return `${plugin.cplugId}/${view}`; },
            features: () => (plugin.installKey ? ['share', 'visible', ...(frameTopics().live() ? ['topic'] : []), ...(surface === 'panel' && onActions ? ['actions'] : []), ...(surface === 'panel' && onMenu ? ['menu'] : [])] : []),
            onActions: takeActions,
            onMenu: takeMenu,
            theme: () => themeValues ?? readTheme(),
            visible: canSee,
            onShare: (value, show) => {
                if (!plugin.installKey) return { ok: false, error: 'unavailable' };
                const shared = shareRelay.share(plugin.installKey, activeNonce, value);
                if (shared.ok && show) onShow?.();
                return shared;
            },
            frame: () => frameEl?.contentWindow ?? null,
            declared: { get routes() { return declared.routes; }, get tools() { return declared.tools; } },
            callRoute: (route, payload) => callViewRoute(plugin.cplugId, route, payload),
            armed: () => surface === 'panel' && armed,
            callTool: (tool, args) => callViewTool(plugin.cplugId, tool, args),
            viewport: () => ({ w: window.innerWidth, h: window.innerHeight }),
            onState: (s) => { viewState = s; },
            onHitRegions: (rects) => { if (surface === 'overlay') declaredRects = rects; },
            onReload: () => { src = null; failed = true; declaredRects = []; actionLimiter.cancel(); onActions?.([]); },
        });
    }

    let bridge = makeBridge(nonce);
    let hasMounted = false;
    let unshare: () => void = () => undefined;
    let trackedViewSrc: string | null | undefined = untrack(() => (viewSrc === undefined ? undefined : viewSrc));

    const watch = createTerminalWatch(terminalRects, () => { layoutTick++; });

    $effect(() => {
        if (surface !== 'overlay' || !declaredRects.length) return;
        const stop = startClock();
        return stop;
    });
    $effect(() => {
        void clock.now;
        if (surface === 'overlay' && declaredRects.length && !document.hidden) watch.look();
    });

    let told = true;
    $effect(() => {
        const now = visible;
        if (now === told) return;
        told = now;
        bridge.send('visible', { visible: now });
        topicHandle?.refresh();
        bridge.release();
    });

    $effect(() => {
        if (viewSrc === undefined) return;
        if (viewSrc !== trackedViewSrc) {
            trackedViewSrc = viewSrc;
            nonce = newNonce();
            bridge = makeBridge(nonce);
            if (hasMounted) {
                unshare();
                unshare = plugin.installKey ? shareRelay.register(plugin.installKey, nonce, (value) => bridge.send('shared', { value })) : () => undefined;
            }
            armed = role === 'menu';
            viewState = '';
            declaredRects = [];
        }
        src = viewSrc;
        failed = false;
    });

    let lastSentTheme = '';
    $effect(() => {
        if (themeValues !== undefined) return;
        return watchTheme((values) => bridge.send('theme', { theme: values }));
    });
    $effect(() => {
        if (themeValues === undefined) {
            lastSentTheme = '';
            return;
        }
        const serialized = JSON.stringify(themeValues);
        if (!lastSentTheme) {
            lastSentTheme = serialized;
            return;
        }
        if (serialized === lastSentTheme) return;
        lastSentTheme = serialized;
        bridge.send('theme', { theme: themeValues });
    });

    onMount(() => {
        armed = role === 'menu';
        const listen = (event: MessageEvent): void => bridge.handle(event);
        const pageShown = (): void => bridge.release();
        document.addEventListener('visibilitychange', pageShown);
        const relayout = (): void => { layoutTick++; };
        window.addEventListener('message', listen);
        window.addEventListener('resize', relayout);
        const stopFocus = keepFocusOut(document, window, () => frameEl, () => surface === 'panel' && armed);
        const disarm = (event: Event): void => { if (armed && event.target !== frameEl) armed = false; };
        document.addEventListener('focusin', disarm, true);
        const rearm = (): void => { armed = false; };
        window.addEventListener('focus', rearm);
        hasMounted = true;
        unshare = plugin.installKey ? shareRelay.register(plugin.installKey, nonce, (value) => bridge.send('shared', { value })) : () => undefined;
        topicHandle = plugin.installKey ? frameTopics().register(plugin.installKey, (name, key) => bridge.send('topic', { name, key }), () => visible) : null;
        if (viewSrc === undefined) {
            fetchViewTicket(plugin.cplugId, view).then(
                (ticket) => { src = ticket.path; },
                () => { failed = true; },
            );
        }
        return () => {
            hasMounted = false;
            window.removeEventListener('message', listen);
            document.removeEventListener('visibilitychange', pageShown);
            window.removeEventListener('resize', relayout);
            stopFocus();
            unshare();
            unshare = () => undefined;
            topicHandle?.release();
            topicHandle = null;
            actionLimiter.cancel();
            document.removeEventListener('focusin', disarm, true);
            window.removeEventListener('focus', rearm);
        };
    });
</script>

{#snippet frame()}
    {#if src}
        <div class="cu-gate">
        {#key src}
        <iframe
            bind:this={frameEl}
            class={surface === 'overlay' ? 'cu-overlay' : 'cu-view'}
            style={surface === 'overlay' ? `clip-path: ${clip}` : undefined}
            sandbox="allow-scripts"
            referrerpolicy="no-referrer"
            title={plugin.name}
            {src}
            data-cplug-view={view}
            data-cplug-role={role}
            data-view-state={viewState || undefined}
            onload={() => {
                bridge.init();
                if (themeValues !== undefined) lastSentTheme = JSON.stringify(themeValues);
                if (plugin.installKey) shareRelay.replay(plugin.installKey, nonce);
                if (!visible) bridge.send('visible', { visible: false });
            }}
        ></iframe>
        {/key}
        {#if surface === 'panel' && !armed}
            <button type="button" class="cu-gate__shield" data-cplug-gate data-base-exempt="an invisible click shield over a frame, not a drawn control" aria-label={t('cplug_ui.panel_activate')}
                onpointerdown={(e) => { if (e.button === 0 && !e.ctrlKey) { e.preventDefault(); arm(); } }}
                onmousedown={(e) => { if (e.button === 0 && !e.ctrlKey) e.preventDefault(); }}
                onclick={(e) => { if (!e.ctrlKey) arm(); }}
                {...(onMenu ? widgetMenuGesture(onMenu) : {})}></button>
        {/if}
        </div>
    {/if}
{/snippet}

{#if surface === 'panel'}
    <HostFrame name={plugin.name} unverified={plugin.unverified} note={failed ? t('cplug_ui.could_not_draw') : null} {bar} {fill} {t}>
        {@render frame()}
    </HostFrame>
{:else if !failed}
    {@render frame()}
{/if}
