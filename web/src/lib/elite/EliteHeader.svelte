
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import type { Translate } from '../sessions/types';
    import * as Logo from './engine/logo';
    import * as Keys from './engine/keys';
    import { boxFrame, callersExtras, fitCol } from './header-paint';
    import type { EliteData } from './elite-data.svelte';
    import type { MenuPanel } from './menu-model';
    import MenuBlock from './MenuBlock.svelte';

    interface Props {
        data: EliteData;
        t: Translate;
        panels: MenuPanel[];
        onPick: (panelId: string, key: string) => void;
        onCmd: (text: string) => void;
        last: string;
        onPlay: () => void;
        promptValue: string;
    }

    let { data, t, panels, onPick, onCmd, last, onPlay, promptValue = $bindable('') }: Props = $props();

    let row1 = $state<HTMLElement | null>(null);
    let logoHost = $state<HTMLElement | null>(null);
    let calls = $state<HTMLElement | null>(null);
    let nodeEl = $state<HTMLElement | null>(null);
    let input = $state<HTMLInputElement | null>(null);
    let cur = $state<HTMLElement | null>(null);
    let focused = $state(false);
    let menu = $state<{ repaint: (swaps?: (() => void)[]) => void } | null>(null);
    let logo: Logo.LogoApi | null = null;

    let inner = $state(60);
    let rowsMax = $state(5);
    let one = $state(true);
    let callsOpen = $state(false);
    const reduced = Logo.reducedMotion();

    const handleWord = $derived(data.handle ?? t('warez.elite.handle.guest'));
    const rows = $derived(data.callers(handleWord).slice(0, rowsMax));
    const crew = $derived(t('warez.elite.callers.crew'));

    const nodeRows = $derived.by((): [string, string, string][][] => {
        const L = (k: string): string => t(`warez.elite.node.${k}`);
        const installs = data.installsSum == null ? L('installs_none') : String(data.installsSum);
        const word = t(`warez.elite.index.${data.index}`);
        const cls = data.index === 'online' ? 'ok' : 'bad';
        const caller: [string, string, string] = [L('caller'), handleWord, ''];
        const baud: [string, string, string] = [L('baud'), L('baud_value'), ''];
        const files: [string, string, string] = [L('files'), String(data.files), ''];
        const index: [string, string, string] = [L('index'), word, cls];
        if (one) {
            const wide: [string, string, string][] = [caller, baud, [L('time'), L('left'), ''], [L('installs'), installs, ''], files, index];
            const w = Math.max(...wide.map((r) => r[0].length));
            return wide.map((r) => [[r[0].padEnd(w), r[1], r[2]]]);
        }
        return [[caller, baud], [[L('left_short'), L('left_value'), ''], [L('installs'), installs, '']], [files, index]];
    });

    function layout(): void {
        if (!row1 || !logoHost || !calls) return;
        const phone = window.innerWidth <= 800;
        const W = row1.clientWidth;
        if (phone || !W) {
            row1.style.gridTemplateColumns = '';
            row1.classList.remove('m1h-wrap');
        } else {
            const nat = (logo?.grid.w ?? 80) * 8;
            const N = 256;
            const G = 12;
            const CMIN = 296;
            let L = Math.min(nat, Math.max(480, W - N - 2 * G - CMIN));
            if (L / nat >= 0.97) L = nat;
            const wrap = L + N + 2 * G + 272 > W;
            row1.classList.toggle('m1h-wrap', wrap);
            row1.style.gridTemplateColumns = wrap ? `minmax(0, 1fr) ${N}px` : `${L}px minmax(0, 1fr) ${N}px`;
            row1.style.gap = `${G}px`;
        }
        logo?.fit();
        inner = Math.floor(calls.clientWidth / 8) - 4;
        rowsMax = phone || Math.floor((calls.clientHeight || 160) / 16) >= 10 ? 5 : 3;
        one = Math.floor((logoHost.clientHeight || 160) / 16) >= 11 || phone;
        schedulePaint();
    }

    let paintQueued = false;
    function schedulePaint(): void {
        if (paintQueued) return;
        paintQueued = true;
        void tick().then(() => {
            paintQueued = false;
            paint();
        });
    }

    function paint(): void {
        const swaps: (() => void)[] = [];
        if (calls) swaps.push(boxFrame(calls, 'double', 14, t('warez.elite.callers.title'), callersExtras));
        if (nodeEl) swaps.push(boxFrame(nodeEl, 'double', 4, t('warez.elite.node.title')));
        if (menu) menu.repaint(swaps);
        else swaps.forEach((swap) => swap());
    }

    $effect(() => {
        void [rows, nodeRows, panels];
        schedulePaint();
    });

    onMount(() => {
        if (!logoHost || !row1) return;
        logo = Logo.draw(logoHost, { baud: 4800, fit: { max: 3, fill: true }, label: '', still: true });
        let lw = 0;
        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => {
            const w = row1?.clientWidth ?? 0;
            if (w !== lw) {
                lw = w;
                layout();
            }
        }) : null;
        ro?.observe(row1);
        if (!ro) addEventListener('resize', layout);
        layout();
        if (cur) Keys.cursor(cur);
        return () => {
            ro?.disconnect();
            removeEventListener('resize', layout);
            logo?.destroy();
            logo = null;
        };
    });

    export function logoArt(): HTMLElement | null {
        return logo?.art ?? null;
    }
    export function hideLogo(hidden: boolean): void {
        if (logoHost) logoHost.style.visibility = hidden ? 'hidden' : '';
    }
    export function replayLogo(): void {
        logo?.replay();
    }
    export function isPromptFocused(): boolean {
        return !!input && document.activeElement === input;
    }
    export function relayout(): void {
        layout();
    }

    function onKeydown(e: KeyboardEvent): void {
        if (e.key !== 'Enter') return;
        e.preventDefault();
        const v = promptValue.trim();
        promptValue = '';
        if (v) onCmd(v);
    }
</script>

<header class="hd m1h" aria-label={t('warez.elite.aria.menu')}>
    <div class="m1h-row1" bind:this={row1}>
        <div class="m1h-logo" bind:this={logoHost}></div>
        <section class="m1h-box m1h-calls" id="m1h-calls" aria-label={t('warez.elite.aria.callers')} data-open={callsOpen ? '1' : ''} bind:this={calls}>
            <div class="m1h-fr" aria-hidden="true"></div>
            <ol class="m1h-cl">
                {#each rows as c}
                    {@const v = t(`warez.elite.callers.${c.verb}`)}
                    <li>
                        {#if inner >= 53}
                            <span class="c-h">{fitCol(c.handle, 9)}</span><span class="c-g">{fitCol(crew, 6)}</span> <span class="c-v">{fitCol(v, 9)}</span> <span class="c-n">{fitCol(c.item, 14)}</span>{#if c.computer}<span class="c-g">{fitCol(t('warez.elite.callers.on', { computer: c.computer }), 8)}</span>{/if}<span class="c-d">{c.date}</span>
                        {:else if inner >= 38}
                            <span class="c-h">{fitCol(c.handle, 10)}</span><span class="c-v">{fitCol(v, 10)}</span><span class="c-n">{fitCol(c.item, 10)}</span><span class="c-d">{c.date}</span>
                        {:else}
                            <span class="c-h">{fitCol(c.handle, 10)}</span><span class="c-v">{fitCol(t(`warez.elite.callers.${c.verb === 'installed' ? 'inst' : 'upd'}`), 5)}</span><span class="c-n">{fitCol(c.item, 10)}</span><span class="c-d">{c.date}</span>
                        {/if}
                    </li>
                {:else}
                    <li><span class="c-v">{t('warez.elite.callers.none')}</span></li>
                {/each}
            </ol>
        </section>
        <section class="m1h-box m1h-node" aria-label={t('warez.elite.aria.node')} bind:this={nodeEl}>
            <div class="m1h-fr" aria-hidden="true"></div>
            <dl class="m1h-nd">
                {#each nodeRows as row}
                    <div>
                        {#each row as [k, v, c], i}{#if i > 0}{'   '}{/if}<span class="n-k">{k}</span> <span class={`n-v${c ? ` ${c}` : ''}`}>{v}</span>{/each}
                    </div>
                {/each}
            </dl>
            {#if reduced}<div class="m1h-opts"><button type="button" class="snd-btn snd-play" onclick={onPlay}>{t('warez.elite.sound.play')}</button></div>{/if}
        </section>
    </div>
    <button type="button" class="m1h-cline" aria-expanded={callsOpen} aria-controls="m1h-calls" onclick={() => { callsOpen = !callsOpen; layout(); }}>
        <span class="m1h-cl-t">{t('warez.elite.callers.line')}</span><span class="m1h-cl-v">{rows[0] ? `${rows[0].handle} ${t(`warez.elite.callers.${rows[0].verb === 'installed' ? 'inst' : 'upd'}`)} ${rows[0].item} ${rows[0].date}` : t('warez.elite.callers.none')}</span><span class="m1h-cl-a" aria-hidden="true">▾</span>
    </button>
    <MenuBlock bind:this={menu} {panels} {onPick} {t} />
    <div class="hd-prompt">
        <label for="hd-in">{t('warez.elite.prompt.label')} <b>{t('warez.elite.prompt.help')}</b>:</label><span class="hd-inwrap"><input id="hd-in" type="text" autocomplete="off" spellcheck="false" data-keep aria-label={t('warez.elite.prompt.aria')} bind:this={input} bind:value={promptValue} onkeydown={onKeydown} onfocus={() => (focused = true)} onblur={() => (focused = false)} /><span class="cur" id="hd-cur" bind:this={cur} style:left={`${promptValue.length * 8}px`} style:opacity={focused ? '1' : ''}></span></span><span class="hd-last">{last}</span>
    </div>
    <h1 class="sr">{t('warez.elite.aria.page')}</h1>
</header>
