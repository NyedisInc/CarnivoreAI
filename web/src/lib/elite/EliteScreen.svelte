
<script lang="ts">
    import { onMount, tick, untrack } from 'svelte';
    import './elite-tokens.css';
    import './elite.css';
    import './elite-board.css';
    import './elite-rail.css';
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import { browserCatalogHost, type CatalogHost } from '../catalog/catalog';
    import { openPublishPage } from '../catalog/publish-entry';
    import { ratingsView, type RatingsView } from '../catalog/ratings';
    import { browserCommunityHost, type CommunityHost } from '../community/community';
    import { openWarezScreen } from '../catalog/warez-host';
    import { t as appT } from '../i18n/index.svelte';
    import { openModalCount } from '../modal';
    import { resourcePush } from '../resource-push/boot';
    import type { Translate } from '../sessions/types';
    import Page from '../../opscenter/ui/Page.svelte';
    import BootStage from './BootStage.svelte';
    import DizPane from './DizPane.svelte';
    import DizSheet from './DizSheet.svelte';
    import EliteHeader from './EliteHeader.svelte';
    import EliteStrip from './EliteStrip.svelte';
    import FileArea from './FileArea.svelte';
    import HelpOverlay from './HelpOverlay.svelte';
    import TaggedPane from './TaggedPane.svelte';
    import { taggedRows } from './batch';
    import { createBoard } from './board.svelte';
    import { dizModel } from './diz-model';
    import { createActions } from './elite-actions';
    import { createEliteData } from './elite-data.svelte';
    import * as Ansi from './engine/ansi';
    import * as Boot from './engine/boot';
    import * as Keys from './engine/keys';
    import * as Logo from './engine/logo';
    import * as Modem from './engine/modem';
    import { dayText } from './elite-prefs';
    import { buildPanels, comboOf } from './menu-model';
    import { activePalette, type Palette } from './palette';

    interface Props {
        host?: CatalogHost;
        community?: CommunityHost;
        t?: Translate;
    }

    const { host, community, t = appT }: Props = $props();

    const TOPIC = 'catalog';
    const POLL_MS = 60_000;
    const ECHO_MS = 1400;
    const DOCK_MS = 420;
    const RAIL_MIN = 1100;
    const DIZ_STEP = 96;
    const SETTLE_MS = 180;

    const tr: Translate = (k, p) => t(k, p);
    const catalogHost = untrack(() => host) ?? browserCatalogHost();
    const communityHost = untrack(() => community) ?? browserCommunityHost();
    const data = createEliteData(catalogHost, tr);

    let open = $state(false);
    let palette = $state<Palette>('carnivore');
    let hint = $state('');
    let live = $state('');
    let noCarrier = $state(false);
    let last = $state('');
    let promptValue = $state('');
    let root = $state<HTMLDivElement | undefined>();
    let stage = $state<{ elements: () => { stage: HTMLElement; dial: HTMLElement; splash: HTMLElement } } | null>(null);
    let area = $state<{ focusCommand: () => void; blurCommand: () => void; toBrowse: () => void; page: (dir: number) => void } | null>(null);
    let header = $state<{ logoArt: () => HTMLElement | null; hideLogo: (h: boolean) => void; isPromptFocused: () => boolean; replayLogo: () => void } | null>(null);
    let diz = $state<{ scrollBy: (dy: number) => void; comment: () => Promise<boolean>; flash: () => void; editing: () => boolean } | null>(null);
    let vw = $state(typeof window === 'undefined' ? 1440 : window.innerWidth);
    let ratings = $state.raw<Record<string, RatingsView>>({});
    let sheetFor = $state<{ id: string; comment: boolean } | null>(null);
    let helpOpen = $state(false);
    let pendingStart: { direct: boolean } | null = null;
    let boardUp = $state(false);
    let opener: HTMLElement | null = null;
    let echoTimer: ReturnType<typeof setTimeout> | null = null;

    const handleWord = $derived(data.handle ?? tr(K.handleGuest));
    const board = createBoard(data, tr, {
        hangup: () => { Boot.hangup(); },
        publish: () => { openPublishPage(); },
        help: () => { helpOpen = true; },
        focusCommand: () => { area?.focusCommand(); },
    });
    const panels = $derived(buildPanels({ census: board.census, on: board.on }, tr));
    const welcome = $derived(data.lastCall ? tr(K.echoWelcome, { handle: handleWord, last: dayText(data.lastCall) }) : tr(K.echoWelcomeFirst, { handle: handleWord }));
    $effect(() => {
        const line = welcome;
        if (open) untrack(() => { if (!board.echo.cmd || board.echo.cmd === 'logon') board.say(line, 'logon'); });
    });

    const wide = $derived(vw >= RAIL_MIN);
    const actions = createActions({ host: catalogHost, data, board, t: tr });
    const rows = $derived(taggedRows(board.tagged, data.listing, data.cards, data.installed));

    /* not in the listing */
    function modelFor(id: string | null) {
        if (!id) return null;
        const item = data.listing.find((i) => String(i.id) === id);
        const card = data.cards.find((c) => c.id === id);
        if (!item || !card) return null;
        const pal = data.catalog.palettes.get(id);
        return dizModel({
            item,
            card,
            held: data.installed[id] ?? [],
            ratings: ratings[id] ?? null,
            installs: data.installs.get(id) ?? null,
            offline: data.offline,
            origin: globalThis.location?.origin ?? '',
            palette: pal ? [pal.page, pal.panel, pal.accent, pal.success, pal.warning, pal.danger] : null,
        }, tr);
    }
    const model = $derived(modelFor(board.sel));
    const sheetModel = $derived(sheetFor ? modelFor(sheetFor.id) : null);

    $effect(() => {
        const id = open ? (sheetFor?.id ?? board.sel) : null;
        if (!id || untrack(() => ratings[id])) return;
        const timer = setTimeout(async () => {
            let view: RatingsView;
            try {
                view = ratingsView(await catalogHost.itemRatings(id));
            } catch {
                return;
            }
            ratings = { ...ratings, [id]: view };
        }, SETTLE_MS);
        return () => clearTimeout(timer);
    });

    function openFile(): void {
        const id = board.sel;
        if (!id) return;
        if (!wide) {
            sheetFor ??= { id, comment: false };
            return;
        }
        board.say(tr(K.echoPane, { name: model?.name ?? id }), 'enter');
        diz?.flash();
    }

    function commentKey(): void {
        const id = board.sel;
        if (!id) { board.say(tr(K.echoNoFile), 'M'); return; }
        board.say(tr(K.echoComment, { name: model?.name ?? id }), 'M');
        if (!wide) sheetFor = { id, comment: true };
        else void diz?.comment();
    }

    let rvTimers: ReturnType<typeof setTimeout>[] = [];
    let rvEls: HTMLElement[] = [];
    let dockAnim: Animation | null = null;
    let flyer: HTMLElement | null = null;

    function targets(): HTMLElement[] {
        const c = root;
        if (!c) return [];
        const all = (sel: string): HTMLElement[] => Array.from(c.querySelectorAll<HTMLElement>(sel));
        const cols = all('.hd-panel').map((p) => Array.from(p.querySelectorAll<HTMLElement>('li')));
        const menu: HTMLElement[] = [];
        for (let i = 0; i < 6; i++) cols.forEach((l) => { const li = l[i]; if (li) menu.push(li); });
        return [...all('.m1h-calls'), ...all('.m1h-node'), ...menu, ...all('.m1h-cline'), ...all('.hd-prompt'), ...all('.m1-strip'), ...all('.fa-area'), ...all('.fa-head'), ...all('.fa-row'), ...all('.m1-rail'), ...all('.fa-echo'), ...all('.fa-cmd')];
    }

    function showAll(): void {
        rvTimers.forEach(clearTimeout);
        rvTimers = [];
        rvEls.forEach((e) => { e.style.opacity = ''; e.style.transition = ''; });
        rvEls = [];
        header?.hideLogo(false);
    }

    function stopDock(): void {
        if (dockAnim) {
            try { dockAnim.cancel(); } catch {  }
            dockAnim = null;
        }
        flyer?.remove();
        flyer = null;
        showAll();
    }

    function splashFn(hostEl: HTMLElement, o: { done: () => void; still: boolean }): { skip: () => void } {
        const st = { done: false };
        const inner = document.createElement('div');
        const cap = document.createElement('div');
        const h1 = document.createElement('h1');
        cap.className = 'boot-cap';
        cap.setAttribute('aria-hidden', 'true');
        h1.className = 'sr';
        h1.textContent = tr(K.title);
        hostEl.replaceChildren(inner, cap, h1);
        if (root) root.scrollTop = 0;
        const lg = Logo.draw(inner, { baud: 4800, still: o.still, fit: { max: 3, fill: true }, onDone: () => { if (!o.still) { cap.textContent = tr(K.bootCaption); dock(); } } });

        function dock(): void {
            const stageEl = stage?.elements().stage;
            const target = header?.logoArt();
            if (st.done || !stageEl || !target || !root) return;
            const sr = stageEl.getBoundingClientRect();
            root.scrollTop = 0;
            const A = lg.art.getBoundingClientRect();
            const T = target.getBoundingClientRect();
            const g = lg.grid;
            header?.hideLogo(true);
            rvEls = targets();
            rvEls.forEach((e) => { e.style.opacity = '0'; e.style.transition = 'opacity .06s linear'; });
            stageEl.classList.add('dock');
            hostEl.style.visibility = 'hidden';
            flyer = Ansi.el(g);
            flyer.classList.add('m1-flyer');
            const sx0 = A.width / (g.w * 8);
            const sy0 = A.height / (g.h * 16);
            const sx1 = T.width / (g.w * 8);
            const sy1 = T.height / (g.h * 16);
            flyer.style.left = `${A.left - sr.left}px`;
            flyer.style.top = `${A.top - sr.top}px`;
            flyer.style.transform = `scale(${sx0},${sy0})`;
            stageEl.appendChild(flyer);
            if (typeof flyer.animate === 'function') {
                dockAnim = flyer.animate(
                    [{ transform: `translate(0px,0px) scale(${sx0},${sy0})` }, { transform: `translate(${T.left - A.left}px,${T.top - A.top}px) scale(${sx1},${sy1})` }],
                    { duration: DOCK_MS, easing: 'cubic-bezier(.4,0,.2,1)', fill: 'forwards' },
                );
                dockAnim.onfinish = () => { header?.hideLogo(false); flyer?.remove(); flyer = null; };
            }
            rvEls.forEach((e, i) => { rvTimers.push(setTimeout(() => { e.style.opacity = '1'; }, 40 + Math.min(i * 5, 420))); });
            rvTimers.push(setTimeout(() => { st.done = true; showAll(); o.done(); }, 40 + Math.min(rvEls.length * 5, 420) + 90));
        }
        return {
            skip: () => {
                st.done = true;
                stopDock();
                lg.skip();
            },
        };
    }

    function startCeremony(direct: boolean): void {
        const els = stage?.elements();
        if (!els) return;
        Boot.start({
            ...els,
            direct,
            hold: 0,
            text: () => ({
                atz: tr(K.bootAtz),
                ok: tr(K.bootOk),
                dial: tr(K.bootDial),
                ring: tr(K.bootRing),
                monAnsam: tr(K.bootMonAnsam),
                monV8: tr(K.bootMonV8),
                monInfo0: tr(K.bootMonInfo0),
                monProbe: tr(K.bootMonProbe),
                connect: tr(K.bootConnect),
                ansi: tr(K.bootAnsi),
                handle: tr(K.bootHandle, { handle: handleWord }),
                password: tr(K.bootPassword),
                node: () => (data.lastCall ? tr(K.bootNode, { last: dayText(data.lastCall) }) : tr(K.bootNodeFirst)),
            }),
            hangupText: () => ({ nocarrier: tr(K.hangupNocarrier), ath: tr(K.hangupAth), hint: tr(K.hangupHint) }),
            splashFn,
            onHint: (kind) => { hint = tr(kind === 'cold' ? K.bootSkipCold : kind === 'redial' ? K.bootSkipRedial : K.bootSkip); },
            onLive: (what) => {
                if (what === 'line') return;
                live = tr(what === 'dialing' ? K.liveDialing : what === 'welcome' ? K.liveWelcome : what === 'ready' ? K.liveReady : K.liveNocarrier);
            },
            onStart: () => {
                noCarrier = false;
                els.stage.classList.remove('dock');
                if (root) root.scrollTop = 0;
            },
            onHangup: () => {
                noCarrier = true;
                Keys.view('board');
            },
            onBack: () => { openWarezScreen(); },
            onDone: () => {
                els.stage.classList.remove('dock');
                data.visit();
                showAll();
                Keys.view('board');
                if (root) root.scrollTop = 0;
            },
        });
    }

    $effect(() => {
        if (open && stage && pendingStart) {
            const p = pendingStart;
            pendingStart = null;
            untrack(() => startCeremony(p.direct));
            if (!p.direct) {
                //  hidden 
                let fired = false;
                const up = (): void => { if (!fired) { fired = true; boardUp = true; } };
                if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => setTimeout(up, 0));
                setTimeout(up, 120);
            }
        }
    });

    function echo(key: string, label: string): void {
        promptValue = key;
        last = tr(K.promptLast, { key, label });
        if (echoTimer) clearTimeout(echoTimer);
        echoTimer = setTimeout(() => { if (!header?.isPromptFocused()) promptValue = ''; }, ECHO_MS);
    }

    function pick(panelId: string, key: string): void {
        const item = panels.find((p) => p.id === panelId)?.items.find((i) => i.key === key);
        if (!item) return;
        if (key !== 'g') echo(key, key === 'a' ? tr(K.itemAllFiles) : item.label);
        board.run(key);
        if (key !== '/' && key !== '?' && key !== 'g') area?.toBrowse();
    }

    function command(text: string): void {
        const k = text.charAt(0) === '/' ? '/' : text.toLowerCase();
        const hit = panels.flatMap((p) => p.items.map((i) => ({ p: p.id, key: i.key }))).find((x) => x.key === k);
        if (hit) {
            pick(hit.p, hit.key);
            return;
        }
        board.say(tr(K.echoUnknown, { key: text }), text);
        echo(text, '?');
    }

    function bindKeys(): void {
        const walk = (by: number): void => { board.move(by); area?.toBrowse(); };
        panels.forEach((p) => p.items.forEach((it) => Keys.bind('board', comboOf(it.key), it.label, () => pick(p.id, it.key))));
        Keys.bind('board', 'shift+Semicolon', tr(K.echoCmdline), () => { area?.focusCommand(); board.say(tr(K.echoCmdline), ':'); });
        Keys.bind('board', 'ArrowDown', tr(K.keyNext), () => walk(1));
        Keys.bind('board', 'ArrowUp', tr(K.keyPrev), () => walk(-1));
        Keys.bind('board', 'KeyJ', tr(K.keyNext), () => walk(1), { hidden: true });
        Keys.bind('board', 'KeyK', tr(K.keyPrev), () => walk(-1), { hidden: true });
        Keys.bind('board', 'PageDown', tr(K.keyPageDown), () => { area?.page(1); area?.toBrowse(); });
        Keys.bind('board', 'PageUp', tr(K.keyPageUp), () => { area?.page(-1); area?.toBrowse(); });
        Keys.bind('board', 'Home', tr(K.keyFirst), () => { board.selectAt(0); area?.toBrowse(); }, { hidden: true });
        Keys.bind('board', 'End', tr(K.keyLast), () => { board.selectAt(board.items.length - 1); area?.toBrowse(); }, { hidden: true });
        Keys.bind('board', 'Space', tr(K.keyTag), (e) => {
            const el = e.target as HTMLElement | null;
            if (el && el.tagName === 'BUTTON') el.click();
            else board.toggleTag();
        });
        Keys.bind('board', 'Enter', tr(K.keyEnter), (e) => {
            const el = e.target as HTMLElement | null;
            if (el && el.tagName === 'BUTTON') el.click();
            else openFile();
        });
        Keys.bind('board', 'shift+Equal', tr(K.keyAdd), () => { void actions.add(); });
        Keys.bind('board', 'Equal', tr(K.keyTry), () => { void actions.tryFile(); });
        Keys.bind('board', 'alt+ArrowDown', tr(K.keyScrollDown), () => { diz?.scrollBy(DIZ_STEP); });
        Keys.bind('board', 'alt+ArrowUp', tr(K.keyScrollUp), () => { diz?.scrollBy(-DIZ_STEP); });
        Keys.bind('board', 'shift+KeyD', tr(K.keyBatchD), () => { void actions.batch('d'); });
        Keys.bind('board', 'shift+KeyU', tr(K.keyBatchU), () => { void actions.batch('u'); });
        Keys.bind('board', 'shift+KeyC', tr(K.keyBatchC), () => { actions.clear(); });
        Keys.bind('board', 'shift+KeyM', tr(K.keyComment), () => { commentKey(); });
        Keys.bind('modal', 'Escape', tr(K.helpClose), () => { helpOpen = false; }, { hidden: true });
        Keys.bind('modal', 'shift+Slash', tr(K.helpClose), () => { helpOpen = false; }, { hidden: true });
        Keys.bind('board', 'Escape', tr(K.keyEscape), () => {
            if (!board.escape()) (document.activeElement as HTMLElement | null)?.blur?.();
        });
        Keys.bind('global', 'alt+KeyL', tr(K.keyReplayLogo), () => { header?.replayLogo(); });
        Keys.bind('global', 'alt+KeyD', tr(K.keyDial), () => { Boot.replay(); });
        Keys.bind('global', 'alt+KeyH', tr(K.keyHangup), () => { Boot.hangup(); });
    }

    export function show(options: { direct?: boolean } = {}): void {
        if (open) return;
        const focused = typeof document !== 'undefined' ? document.activeElement : null;
        opener = focused instanceof HTMLElement ? focused : null;
        palette = activePalette();
        last = tr(K.promptLastNone);
        promptValue = '';
        noCarrier = false;
        board.reset();
        ratings = {};
        sheetFor = null;
        helpOpen = false;
        board.say(welcome, 'logon');
        pendingStart = { direct: options.direct ?? /^#elite\/board$/.test(globalThis.location?.hash ?? '') };
        boardUp = pendingStart.direct;
        open = true;
        Keys.view('board');
        data.begin();
    }

    export function close(): void {
        if (!open) return;
        Boot.destroy();
        stopDock();
        if (echoTimer) clearTimeout(echoTimer);
        echoTimer = null;
        pendingStart = null;
        sheetFor = null;
        helpOpen = false;
        open = false;
        if (opener && document.contains(opener)) opener.focus();
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    onMount(() => {
        const detach = Keys.attach({
            modalOpen: () => helpOpen,
            claims: (e) => {
                if (!open || openModalCount() > 0 || sheetFor) return false;
                const el = e.target as Node | null;
                return !el || el === document.body || el === document.documentElement || !!root?.contains(el);
            },
        });
        bindKeys();
        const offPush = resourcePush().pushOrPoll(() => { if (open) data.refresh(); }, POLL_MS, [TOPIC]);
        return () => {
            detach();
            offPush();
            Keys.clear();
            Boot.destroy();
            stopDock();
        };
    });

    $effect(() => {
        if (!open || typeof MutationObserver === 'undefined') return;
        const mo = new MutationObserver(() => { palette = activePalette(); });
        mo.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'class', 'data-theme'] });
        return () => mo.disconnect();
    });
</script>

<svelte:window bind:innerWidth={vw} />

{#if open}
    <Page title={tr(K.title)} class="elite" data-palette={palette} bind:root>
        {#if boardUp}
        <div class="m1c">
            <EliteHeader
                bind:this={header}
                {data}
                t={tr}
                {panels}
                onPick={pick}
                onCmd={command}
                {last}
                onPlay={() => { Modem.preview(); }}
                bind:promptValue
            />
            <EliteStrip files={data.files} t={tr} />
            <div class="m1-cols">
                <div class="m1-browse"><FileArea bind:this={area} {board} {data} t={tr} onOpen={openFile} tapOpens={!wide} /></div>
                <aside class="m1-rail" id="elite-rail" aria-label={tr(K.ariaRail)}>
                    {#if wide}
                        <DizPane
                            bind:this={diz}
                            {model}
                            offline={data.offline}
                            t={tr}
                            host={communityHost}
                            say={(text) => board.say(text, 'M')}
                            onAdd={() => { void actions.add(board.sel); }}
                            onTry={() => { void actions.tryFile(); }}
                            onAll={() => board.run('a')}
                        />
                    {/if}
                    <TaggedPane {rows} offline={data.offline} t={tr} onDownload={() => { void actions.batch('d'); }} onUpdate={() => { void actions.batch('u'); }} onClear={() => { actions.clear(); }} />
                </aside>
            </div>
        </div>
        {/if}
        {#if sheetFor && sheetModel}
            <DizSheet
                model={sheetModel}
                offline={data.offline}
                t={tr}
                host={communityHost}
                say={(text) => board.say(text, 'M')}
                onAdd={() => { void actions.add(sheetFor?.id ?? board.sel); }}
                onTry={() => { void actions.tryFile(sheetFor?.id ?? board.sel); }}
                onClose={() => { sheetFor = null; }}
                openComment={sheetFor.comment}
            />
        {/if}
        {#if helpOpen}<HelpOverlay t={tr} onClose={() => { helpOpen = false; }} />{/if}
        <BootStage bind:this={stage} {hint} showBack={noCarrier} backLabel={tr(K.hangupBack)} onBack={() => { openWarezScreen(); }} />
        <div class="sr" aria-live="polite">{live}</div>
    </Page>
{/if}