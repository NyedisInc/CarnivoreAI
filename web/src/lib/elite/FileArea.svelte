<!-- could not be read -->
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
    import type { CardView } from '../catalog/card';
    import type { Translate } from '../sessions/types';
    import type { Board } from './board.svelte';
    import type { EliteData } from './elite-data.svelte';
    import * as Ansi from './engine/ansi';
    import * as Art from './engine/art';
    import * as Keys from './engine/keys';
    import { headText, layoutOf, pad, rowLines, sizeText, tierOf, type RowInput } from './file-rows';
    import FileRows from './FileRows.svelte';

    interface Props {
        board: Board;
        data: EliteData;
        t: Translate;
        onOpen?: () => void;
        tapOpens?: boolean;
    }

    const { board, data, t, onOpen, tapOpens = false }: Props = $props();

    const BIG_ABOVE = 800;
    const KIND_WORD: Record<string, string> = { skill: 'skills', theme: 'themes', mod: 'mods', plugin: 'plugins' };

    let section = $state<HTMLElement | null>(null);
    let list = $state<HTMLElement | null>(null);
    let input = $state<HTMLInputElement | null>(null);
    let cur = $state<HTMLElement | null>(null);
    let width = $state(0);
    let vw = $state(typeof window === 'undefined' ? 1200 : window.innerWidth);
    let typing = $state(false);
    let value = $state('');
    let caret = $state(0);
    let gutter = $state('');

    const big = $derived(vw > BIG_ABOVE);
    const fs = $derived(big ? Math.max(14, Math.floor((width || 640) / 40)) : (width || 640) < 620 ? 14 : 16);
    const cw = $derived(fs / 2);
    const cols = $derived(Math.max(36, Math.floor((width || 640) / cw)));
    const lay = $derived(layoutOf(cols));
    const phone = $derived(tierOf(cols) === 'phone');
    const reason = $derived(data.failure ?? '');

    function kindTag(kind: string | null): string {
        const key = `warez.elite.kind.${kind}`;
        const word = kind ? t(key) : '';
        return `[${word && word !== key ? word : (kind ?? '').slice(0, 3).toUpperCase()}]`;
    }
    function rowOf(c: CardView): RowInput {
        const held = c.id ? data.installed[c.id] : undefined;
        const update = !!held?.some((r) => r.update_available === true);
        return {
            name: c.headline ?? c.id ?? '',
            kind: c.kind ?? '',
            kindTag: kindTag(c.kind),
            brief: c.brief ?? '',
            dl: c.id && data.installs.has(c.id) ? data.installs.get(c.id)! : null,
            mark: update ? t(K.markUpd) : held?.length ? t(K.markInst) : '',
            tagged: !!c.id && board.tagged.has(c.id),
        };
    }

    const rows = $derived(board.items.map((c, i) => ({ key: c.renderKey, id: c.id ?? '', lines: rowLines(rowOf(c), i, lay), isNew: !!c.id && data.marked.has(c.id), label: `${c.headline}, ${kindTag(c.kind)}${c.verdict ? `, ${c.verdict}` : ''}` })));
    const head = $derived(headText(lay, { num: t(K.colNum), tag: t(K.colTag), name: t(K.colName), kind: t(K.colKind), dl: t(K.colDl), brief: t(K.colBrief) }));

    const areaLabel = $derived.by(() => {
        const q = board.q;
        const parts: string[] = [];
        if (q.kind !== 'all') parts.push(KIND_WORD[q.kind] ? t(`warez.elite.item.${KIND_WORD[q.kind]}`) : q.kind);
        if (q.state !== 'any') parts.push(t(`warez.elite.item.${q.state}`));
        if (q.q) parts.push(`"${q.q}"`);
        return t(K.areaLine, { n: board.areaNumber, name: parts.length ? parts.join(' / ') : t(K.itemAll) });
    });
    const areaCount = $derived(t(data.offline ? K.areaCached : K.areaCount, { n: board.items.length, total: data.files }));
    const areaBar = $derived.by(() => {
        const n = phone ? 8 : 14;
        const k = Math.round(Math.max(0, Math.min(1, data.files ? board.items.length / data.files : 0)) * n);
        return [k, n - k];
    });
    const emptyText = $derived(board.q.q ? t(K.emptyQuery, { q: board.q.q }) : t(K.emptyView));

    function rowH(): number {
        return 2 * fs;
    }

    function paintGutter(): void {
        if (!list) return;
        const n = Math.max(3, Math.round(list.clientHeight / fs));
        const sh = list.scrollHeight;
        const ch = list.clientHeight;
        const track = n - 2;
        const scrolls = sh > ch + 1;
        const thumb = scrolls ? Math.max(1, Math.round((track * ch) / sh)) : 0;
        const pos = scrolls ? Math.round(((track - thumb) * list.scrollTop) / (sh - ch)) : 0;
        const out = ['▲'];
        for (let i = 0; i < track; i++) out.push(i >= pos && i < pos + thumb ? '█' : '░');
        out.push('▼');
        gutter = out.join('\n');
    }

    function ensureVisible(): void {
        const el = list?.querySelector<HTMLElement>('.sel');
        if (!el || !list) return;
        const top = el.offsetTop;
        const bottom = top + el.offsetHeight;
        if (top < list.scrollTop) list.scrollTop = top;
        else if (bottom > list.scrollTop + list.clientHeight) list.scrollTop = bottom - list.clientHeight;
    }

    $effect(() => {
        void board.sel;
        void rows;
        void fs;
        void tick().then(() => {
            ensureVisible();
            paintGutter();
        });
    });

    export function focusCommand(): void {
        try {
            input?.focus({ preventScroll: true });
        } catch {
            input?.focus();
        }
    }
    export function blurCommand(): void {
        input?.blur();
    }
    export function page(dir: number): void {
        board.move(dir * Math.max(1, Math.floor((list?.clientHeight ?? 0) / rowH()) - 1));
    }
    /* the whole file */
    export function toBrowse(): void {
        const host = section?.closest<HTMLElement>('.oc-page');
        if (!section || !host || typeof host.scrollBy !== 'function') return;
        const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
        const behavior = reduced ? 'auto' : 'smooth';
        const c = host.getBoundingClientRect();
        const f = section.getBoundingClientRect();
        const over = f.bottom - c.bottom + 8;
        if (over > 0 && f.top - over > c.top - 4) host.scrollBy({ top: over, behavior });
        else if (over > 0) host.scrollBy({ top: f.top - c.top - 4, behavior });
    }

    function onKeydown(e: KeyboardEvent): void {
        if (e.key === 'Enter') {
            e.preventDefault();
            const v = value;
            value = '';
            caret = 0;
            if (!v.trim()) onOpen?.();
            else board.command(v);
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            board.move(1);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            board.move(-1);
        } else if (e.key === 'PageDown') {
            e.preventDefault();
            page(1);
        } else if (e.key === 'PageUp') {
            e.preventDefault();
            page(-1);
        } else if (e.key === ' ' && !value) {
            e.preventDefault();
            board.toggleTag();
        }
    }
    function place(): void {
        caret = input?.selectionStart ?? 0;
    }
    function open(e: MouseEvent): void {
        const row = (e.target as HTMLElement).closest<HTMLElement>('.fa-row');
        if (!row?.dataset.id) return;
        board.select(row.dataset.id);
        onOpen?.();
    }
    function pick(e: MouseEvent): void {
        const row = (e.target as HTMLElement).closest<HTMLElement>('.fa-row');
        if (!row?.dataset.id) return;
        board.select(row.dataset.id);
        if ((e.target as HTMLElement).closest('[data-tag]')) board.toggleTag(row.dataset.id);
        else if (tapOpens) onOpen?.();
    }

    function art(node: HTMLElement, make: () => Ansi.Grid): { destroy: () => void } {
        const a = Ansi.el(make());
        a.style.position = 'relative';
        node.appendChild(a);
        const fitIt = (): void => {
            const fw = node.clientWidth;
            const aw = a.offsetWidth;
            if (fw && aw > fw) {
                const k = fw / aw;
                a.style.transformOrigin = '0 0';
                a.style.transform = `scale(${k})`;
                node.style.height = `${Math.ceil(96 * Math.min(1, k))}px`;
            } else {
                a.style.transform = '';
                node.style.height = '';
            }
        };
        fitIt();
        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(fitIt) : null;
        ro?.observe(node);
        return { destroy: () => ro?.disconnect() };
    }
    const noCarrier = (): Ansi.Grid => Art.label(t(K.hangupNocarrier), { fg: 12, sh: 1 });

    onMount(() => {
        if (cur) Keys.cursor(cur);
        const measure = (): void => { width = section?.clientWidth ?? 0; };
        measure();
        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
        if (section) ro?.observe(section);
        paintGutter();
        return () => ro?.disconnect();
    });
</script>

<svelte:window bind:innerWidth={vw} />

<section
    class="farea"
    aria-label={t(K.ariaArea)}
    style:--fa-rows="9"
    style:font-size={big ? `${fs}px` : undefined}
    data-big={big ? '1' : undefined}
    data-cw={cw < 7.5 ? '7' : '8'}
    data-tier={lay.t}
    class:typing
    bind:this={section}
>
    <div class="fa-area">
        <span class="ar">{phone ? areaLabel : pad(areaLabel, 30)}</span>{' '}<span class="fa-bar" aria-hidden="true"><b>{'▓'.repeat(areaBar[0]!)}</b>{'░'.repeat(areaBar[1]!)}</span>{' '}<span class="ct">{areaCount}</span>{#if !phone}<span class="tg">{' '}{t(K.areaTagged)} <b>{board.tagged.size}</b> {board.tagged.size ? sizeText(board.taggedBytes) : ''}</span>{/if}
    </div>
    <div class="fa-head" aria-hidden="true" hidden={phone}>{head}</div>
    <div class="fa-wrap">
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (the keys live on the command line, the page claims them) -->
        <div class="fa-list" role="listbox" aria-label={t(K.ariaFiles)} aria-multiselectable="true" tabindex="-1" bind:this={list} onscroll={paintGutter} onclick={pick} ondblclick={open}>
            {#if data.offline}
                <div class="m1-nocar" role="status" use:art={noCarrier}><span class="sr">{t(K.hangupNocarrier)}</span></div>
                {#if board.items.length}
                    <div class="fa-msg dm">{t(K.nocarrierCached)}</div>
                {:else if data.files === 0}
                    <div class="fa-msg dm">{t(K.nocarrierNone)}</div>
                    <div class="fa-msg dm">{t(K.emptyUnreadable, { reason })}</div>
                {/if}
            {/if}{#if board.items.length}
                <FileRows {rows} sel={board.sel} />
            {:else if !data.offline && !data.loading}
                <div class="m1-empty">
                    <div class="m1-skull" aria-hidden="true" use:art={() => Art.skull()}></div>
                    <div class="m1-empty-t" role="status">{emptyText} {t(K.emptyPressBefore)} <button type="button" class="m1-akey" onclick={() => board.run('a')}>a</button> {t(K.emptyPressAfter)}</div>
                </div>
            {/if}
        </div><div class="fa-sb" aria-hidden="true">{gutter}</div>
    </div>
    <div class="fa-echo" role="status" aria-live="polite">
        {#if board.echo.cmd}<span class="pr">{`> ${board.echo.cmd}`}</span>{'  '}{/if}<span class="rs">{board.echo.text}</span>
    </div>
    <div class="fa-cmd">
        <label for="fa-in-elite">{t(K.cmdLabel)} <b>{t(K.promptHelp)}</b>:</label><span class="fa-inwrap"><input
                id="fa-in-elite"
                type="text"
                autocomplete="off"
                spellcheck="false"
                data-keep
                aria-label={t(K.cmdAria)}
                aria-activedescendant={board.sel ? `fa-${board.sel.replace(/[^a-z0-9_-]/gi, '_')}` : undefined}
                bind:this={input}
                bind:value
                onkeydown={onKeydown}
                oninput={place}
                onkeyup={place}
                onclick={place}
                onfocus={() => { typing = true; if (cur) cur.style.opacity = '1'; }}
                onblur={() => { typing = false; if (cur) cur.style.opacity = ''; }}
            /><span class="cur" bind:this={cur} style:left={`${caret * cw}px`}></span></span>
    </div>
</section>
