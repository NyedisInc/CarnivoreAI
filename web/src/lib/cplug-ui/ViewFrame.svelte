
<script lang="ts">
    import { onMount } from 'svelte';
    import { clock, startClock } from '../../opscenter/lib/frozen-clock.svelte';
    import type { Translate } from '../sessions/types';
    import type { CplugItem } from '../plugins-page/cplugs-adapter';
    import { callViewRoute, fetchViewTicket } from './api';
    import { createBridge, newNonce, type ViewRole } from './bridge';
    import { readTheme, watchTheme } from './frame-theme';
    import { keepFocusOut } from './focus-return';
    import { clipPath, createTerminalWatch, enabledRects, type Rect } from './hit-regions';
    import HostFrame from './HostFrame.svelte';
    import { frameTopics, type FrameTopicHandle } from './frame-topics';
    import { shareRelay } from './share-relay';

    interface Props {
        plugin: Pick<CplugItem, 'cplugId' | 'name' | 'unverified' | 'declared' | 'installKey'>;
        view: string;
        surface: 'panel' | 'overlay';
        viewRole?: ViewRole;
        onShow?: () => void;
        visible?: boolean;
        t: Translate;
    }

    const { plugin, view, surface, viewRole, onShow, visible = true, t }: Props = $props();
    const role = $derived<ViewRole>(viewRole ?? surface);
    const declared = $derived(plugin.declared ?? { routes: [], tools: [] });
    const nonce = newNonce();
    let src = $state<string | null>(null);
    let failed = $state(false);
    let viewState = $state('');
    let declaredRects = $state<Rect[]>([]);
    let layoutTick = $state(0);
    let frameEl = $state<HTMLIFrameElement | null>(null);
    let armed = $state(false);

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

    const bridge = createBridge({
        nonce,
        get role() { return role; },
        features: () => (plugin.installKey ? ['share', 'visible', ...(frameTopics().live() ? ['topic'] : [])] : []),
        theme: () => readTheme(),
        onShare: (value, show) => {
            if (!plugin.installKey) return { ok: false, error: 'unavailable' };
            const shared = shareRelay.share(plugin.installKey, nonce, value);
            if (shared.ok && show) onShow?.();
            return shared;
        },
        frame: () => frameEl?.contentWindow ?? null,
        declared: { get routes() { return declared.routes; }, get tools() { return declared.tools; } },
        callRoute: (route, payload) => callViewRoute(plugin.cplugId, route, payload),
        viewport: () => ({ w: window.innerWidth, h: window.innerHeight }),
        onState: (s) => { viewState = s; },
        onHitRegions: (rects) => { if (surface === 'overlay') declaredRects = rects; },
        onReload: () => { src = null; failed = true; declaredRects = []; },
    });

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
    });

    onMount(() => {
        armed = role === 'menu';
        const listen = (event: MessageEvent): void => bridge.handle(event);
        const relayout = (): void => { layoutTick++; };
        window.addEventListener('message', listen);
        window.addEventListener('resize', relayout);
        const stopFocus = keepFocusOut(document, window, () => frameEl, () => surface === 'panel' && armed);
        const disarm = (event: Event): void => { if (armed && event.target !== frameEl) armed = false; };
        document.addEventListener('focusin', disarm, true);
        const rearm = (): void => { armed = false; };
        window.addEventListener('focus', rearm);
        const unshare = plugin.installKey ? shareRelay.register(plugin.installKey, nonce, (value) => bridge.send('shared', { value })) : () => undefined;
        topicHandle = plugin.installKey ? frameTopics().register(plugin.installKey, (name, key) => bridge.send('topic', { name, key }), () => visible) : null;
        const stopTheme = watchTheme((values) => bridge.send('theme', { theme: values }));
        fetchViewTicket(plugin.cplugId, view).then(
            (ticket) => { src = ticket.path; },
            () => { failed = true; },
        );
        return () => {
            window.removeEventListener('message', listen);
            window.removeEventListener('resize', relayout);
            stopFocus();
            stopTheme();
            unshare();
            topicHandle?.release();
            topicHandle = null;
            document.removeEventListener('focusin', disarm, true);
            window.removeEventListener('focus', rearm);
        };
    });
</script>

{#snippet frame()}
    {#if src}
        <div class="cu-gate">
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
            onload={() => { bridge.init(); if (plugin.installKey) shareRelay.replay(plugin.installKey, nonce); if (!visible) bridge.send('visible', { visible: false }); }}
        ></iframe>
        {#if surface === 'panel' && !armed}
            <button type="button" class="cu-gate__shield" data-cplug-gate data-base-exempt="an invisible click shield over a frame, not a drawn control" title={t('cplug_ui.panel_activate')} aria-label={t('cplug_ui.panel_activate')}
                onclick={() => { armed = true; frameEl?.focus(); }}></button>
        {/if}
        </div>
    {/if}
{/snippet}

{#if surface === 'panel'}
    <HostFrame name={plugin.name} unverified={plugin.unverified} note={failed ? t('cplug_ui.could_not_draw') : null} {t}>
        {@render frame()}
    </HostFrame>
{:else if !failed}
    {@render frame()}
{/if}
