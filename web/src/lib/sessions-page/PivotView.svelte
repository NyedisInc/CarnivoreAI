
<script lang="ts">
    import RowActionButton from './RowActionButton.svelte';
    import { tick } from 'svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import Button from '../base/Button.svelte';
    import Segmented from '../base/Segmented.svelte';
    import Select from '../base/Select.svelte';
    import { animationTypeOff } from '../motion/animation-types';
    import { motionReduced } from '../motion/motion';
    import { ageFormatter } from '../projects-shared/format';
    import { projectColorVar } from '../project-colors/palette';
    import { companyList } from '../companies';
    import { companyTint } from '../sidebar-shell/tint';
    import { projectColorOf } from '../project-colors/store.svelte';
    import { providerMark } from '../sessions/agent-marks';
    import type { Translate } from '../sessions/types';
    import { fleetCounts, type PageRow } from './filters';
    import { latestView } from './latest-line';
    import { AXIS_ORDER, buildPivot, readPrefs, unavailable, writePrefs, type AxisKey, type Bucket, type PivotContext, type Tally } from './pivot-axes';
    import RowLed from './RowLed.svelte';
    import { rowAction, type RowAction } from './row-action';
    import type { SessionsData } from './sessions-data.svelte';
    import './sessions-list.css';
    import './pivot.css';

    interface Props {
        rows: readonly PageRow[];
        data: SessionsData;
        t: Translate;
        now: () => number;
        selected?: string | null;
        panelOpen?: boolean;
        historyFailed?: boolean;
        find?: string;
        onPreview: (sessionUuid: string | null) => void;
        onAct: (kind: RowAction, row: PageRow) => void;
    }
    const { rows, data, t, now, selected = null, panelOpen = false, historyFailed = false, find = '', onPreview, onAct }: Props = $props();

    const CAP = 6;
    const ROW_FOLD = 30;
    const DENSITIES = ['detail', 'compact'] as const;
    type Dens = (typeof DENSITIES)[number];
    const RH_W = 216;
    const COL_MIN = 192;

    const prefs = readPrefs();
    let rowAxis = $state<AxisKey>(prefs.rows);
    let colAxis = $state<AxisKey>(prefs.cols);
    let dens = $state<'detail' | 'compact'>(prefs.dens);
    let iso = $state<{ side: 'r' | 'c'; id: string } | null>(null);
    let expanded = $state<Record<string, boolean>>({});
    let phoneSel = $state<Record<string, string | null>>({});
    let fold = $state(false);
    let hover = $state<{ name: string; r: string; c: string } | null>(null);
    let phone = $state(false);
    let scroller = $state<HTMLDivElement | undefined>();
    let scrollW = $state(0);

    $effect(() => {
        if (typeof matchMedia === 'undefined') return;
        const mq = matchMedia('(max-width: 700px)');
        phone = mq.matches;
        const on = (): void => void (phone = mq.matches);
        mq.addEventListener('change', on);
        return () => mq.removeEventListener('change', on);
    });

    $effect(() => {
        if (!scroller || typeof ResizeObserver === 'undefined') return;
        const watch = new ResizeObserver(() => (scrollW = scroller?.clientWidth ?? 0));
        watch.observe(scroller);
        return () => watch.disconnect();
    });

    const flags = $derived({ historyFailed, listingDown: data.listingDown });
    const axisOptions = $derived(
        AXIS_ORDER.map((k) => {
            const why = unavailable(k, flags);
            return { value: k, label: why ? `${axisName(k)} (${t(`sessions.page.pivot.unavailable.${why}`)})` : axisName(k), disabled: why !== null };
        }),
    );

    function firstOk(avoid?: AxisKey): AxisKey {
        return AXIS_ORDER.find((k) => k !== avoid && !unavailable(k, flags)) ?? 'project';
    }
    const rAx = $derived<AxisKey>(unavailable(rowAxis, flags) ? firstOk(colAxis) : rowAxis);
    const cAx = $derived<AxisKey>(unavailable(colAxis, flags) || colAxis === rAx ? firstOk(rAx) : colAxis);

    const ctx = $derived<PivotContext>({
        t,
        now: now(),
        sig: data,
        usage: data.usage,
        conversations: data.conversations,
        find,
        noCompany: t('sessions.page.filter.no_company'),
        thisComputer: t('sessions.page.filter.this_computer'),
    });
    const companyColor = (name: string): string => companyTint(companyList().find((c) => c.name === name)?.id ?? null) ?? 'var(--oc-text-muted)';
    const model = $derived(buildPivot(rows, rAx, cAx, ctx));
    const age = $derived(ageFormatter(t, now));
    const oldestDays = $derived(fleetCounts(rows, data, now()).oldestDays);

    const shownRows = $derived(model.rows.length > ROW_FOLD && !fold ? model.rows.slice(0, ROW_FOLD) : model.rows);
    const foldedRows = $derived(model.rows.slice(shownRows.length));

    const fitK = $derived(panelOpen && !phone && scrollW > RH_W ? Math.max(1, Math.floor((scrollW - RH_W) / COL_MIN)) : 0);
    const fitW = $derived(fitK ? Math.floor((scrollW - RH_W) / fitK) : 0);

    const axisName = (k: AxisKey): string => t(`sessions.page.pivot.axis.${k}`);
    const sessionsOf = (n: number): string => t(`sessions.page.pivot.sessions.${n === 1 ? 'one' : 'other'}`, { n });
    const nounOf = (k: AxisKey, n: number): string => t(`sessions.page.pivot.noun.${k}.${n === 1 ? 'one' : 'other'}`, { n });
    function labelOf(side: 'r' | 'c', id: string): string {
        return (side === 'r' ? model.rows : model.cols).find((b) => b.id === id)?.label ?? id;
    }
    const keyOf = (r: string, c: string): string => `${r}|${c}`;
    const inCell = (r: string, c: string): readonly PageRow[] => model.cells.get(keyOf(r, c)) ?? [];
    const dimmed = (r: string, c: string): boolean => iso !== null && (iso.side === 'r' ? r !== iso.id : c !== iso.id);

    const slice = $derived.by(() => {
        if (!iso) return null;
        let n = 0;
        const other = new Set<string>();
        for (const [k, list] of model.cells) {
            const [r, c] = k.split('|') as [string, string];
            if (iso.side === 'r' ? r !== iso.id : c !== iso.id) continue;
            n += list.length;
            other.add(iso.side === 'r' ? c : r);
        }
        return { n, spans: other.size };
    });
    const groupsShown = $derived(model.rows.filter((r) => model.rowTally.has(r.id)).length);

    function remember(): void {
        writePrefs({ rows: rAx, cols: cAx, dens });
    }

    function snap(): Map<string, [number, number]> {
        const out = new Map<string, [number, number]>();
        for (const el of scroller?.querySelectorAll<HTMLElement>('[data-key]') ?? []) {
            const b = el.getBoundingClientRect();
            out.set(el.dataset.key as string, [b.left, b.top]);
        }
        return out;
    }

    function glide(before: Map<string, [number, number]>): void {
        if (motionReduced() || animationTypeOff('layout-moves')) return;
        for (const el of scroller?.querySelectorAll<HTMLElement>('[data-key]') ?? []) {
            const from = before.get(el.dataset.key as string);
            if (!from || typeof el.animate !== 'function') continue;
            const b = el.getBoundingClientRect();
            const dx = from[0] - b.left;
            const dy = from[1] - b.top;
            if (dx || dy) el.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }], { duration: 280, easing: 'ease-out' });
        }
    }

    async function moving(change: () => void): Promise<void> {
        const before = phone ? null : snap();
        change();
        remember();
        if (!before) return;
        await tick();
        glide(before);
    }

    function pickRows(k: AxisKey): Promise<void> {
        return moving(() => {
            if (k === cAx) colAxis = rAx;
            rowAxis = k;
            reset();
        });
    }

    function pickCols(k: AxisKey): Promise<void> {
        return moving(() => {
            if (k === rAx) rowAxis = cAx;
            colAxis = k;
            reset();
        });
    }

    function swap(): Promise<void> {
        return moving(() => {
            const next = iso ? ({ side: iso.side === 'r' ? 'c' : 'r', id: iso.id } as const) : null;
            const r = rAx;
            rowAxis = cAx;
            colAxis = r;
            reset();
            iso = next;
        });
    }

    function reset(): void {
        iso = null;
        phoneSel = {};
        expanded = {};
        fold = false;
    }

    function isolate(side: 'r' | 'c', id: string): void {
        iso = iso && iso.side === side && iso.id === id ? null : { side, id };
        if (iso?.side === 'c') phoneSel = {};
    }

    function setDens(next: Dens): void {
        dens = next;
        remember();
    }

    function cross(r: PageRow, rid: string, cid: string): void {
        hover = { name: r.s.label ?? r.s.title, r: rid, c: cid };
    }

    const keepsFocus = (e: FocusEvent | MouseEvent, el: HTMLElement): boolean => Boolean(e.relatedTarget instanceof Node && el.contains(e.relatedTarget));

    function walk(e: KeyboardEvent): void {
        const target = e.target instanceof Element ? e.target.closest<HTMLElement>('.sp-pv-cb') : null;
        if (!target || !['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
        const all = [...(scroller?.querySelectorAll<HTMLElement>('.sp-pv-cb') ?? [])].filter((b) => !b.closest('[data-dim]'));
        const i = all.indexOf(target);
        const j = e.key === 'Home' ? 0 : e.key === 'End' ? all.length - 1 : e.key === 'ArrowRight' || e.key === 'ArrowDown' ? Math.min(all.length - 1, i + 1) : Math.max(0, i - 1);
        e.preventDefault();
        all[j]?.focus();
        all[j]?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    $effect(() => {
        const id = selected;
        void fitW;
        if (!id || !panelOpen || phone || !scroller) return;
        void tick().then(() => {
            const sc = scroller;
            const chip = [...(sc?.querySelectorAll<HTMLElement>('[data-key]') ?? [])].find((el) => el.dataset.key === id);
            if (!sc || !chip) return;
            chip.scrollIntoView?.({ block: 'nearest' });
            if (!fitK || !fitW) return;
            const grid = sc.firstElementChild as HTMLElement;
            const idx = Math.floor((chip.getBoundingClientRect().left - grid.getBoundingClientRect().left - RH_W + 2) / fitW);
            const first = Math.round(sc.scrollLeft / fitW);
            if (idx < first || idx >= first + fitK) sc.scrollLeft = Math.max(0, Math.min(idx, model.cols.length - fitK)) * fitW;
        });
    });
</script>

{#snippet mark(b: Bucket)}
    {#if b.provider}
        <span class="sp-pv-pico" role="img" aria-label={b.provider}>{@html providerMark(b.provider, 14).svg}</span>
    {:else if b.letter}
        <span class="sp-pchip" style:--pc={b.companyName !== undefined ? companyColor(b.companyName) : projectColorVar(projectColorOf(b.projectId ?? null))}>{b.letter}</span>
    {/if}
{/snippet}

{#snippet head(side: 'r' | 'c', b: Bucket, tally: Tally | undefined, flat: boolean)}
    {@const tl = tally ?? { n: 0, live: 0, newest: 0 }}
    {@const pressed = iso !== null && iso.side === side && iso.id === b.id}
    <Button variant="row" data-hb data-ih={side} data-id={b.id} aria-pressed={pressed} onclick={() => isolate(side, b.id)}>
        {#if side === 'c' && !flat}
            <span class="sp-pv-t1"><span class="sp-pv-nm">{b.label}</span><span class="sp-pv-fig">{tl.n}</span></span>
            {#if b.sub}<span class="sp-pv-t2" class:sp-pv-rng={b.wide}>{b.sub}</span>{/if}
        {:else}
            <span class="sp-pv-t1">{@render mark(b)}<span class="sp-pv-nm">{b.label}</span></span>
            {#if b.sub}<span class="sp-pv-t2">{b.sub}</span>{/if}
            <span class="sp-pv-t3"><b>{tl.live}</b> {t('sessions.page.pivot.live')} · {tl.n} {t('sessions.page.pivot.total')}{#if tl.newest} · {age(new Date(tl.newest).toISOString())}{/if}</span>
        {/if}
    </Button>
{/snippet}

{#snippet chip(r: PageRow, rid: string, cid: string)}
    {@const live = data.live(r.s)}
    {@const view = latestView(r.s, data.latest[r.s.session_uuid], now(), t)}
    {@const name = r.s.label ?? r.s.title}
    {@const action = rowAction(r.s)}
    {@const mk = providerMark(r.provider, 12)}
    <div class="sp-pv-chip" role="group" aria-label={name} data-key={r.s.session_uuid} data-id={r.s.session_uuid} aria-current={selected === r.s.session_uuid ? 'true' : undefined} data-miss={model.misses.has(r.s.session_uuid) ? '' : undefined} onmouseenter={() => cross(r, rid, cid)} onmouseleave={(e) => !keepsFocus(e, e.currentTarget) && (hover = null)} onfocusin={() => cross(r, rid, cid)} onfocusout={(e) => !keepsFocus(e, e.currentTarget) && (hover = null)}>
        <Button variant="row" data-cb onclick={() => onPreview(selected === r.s.session_uuid ? null : r.s.session_uuid)}>
            <span class="sp-pv-led"><RowLed row={r} {live} asleepUnread={data.asleepUnread(r.s.session_uuid)} /></span>
            <span class="sp-pv-name">{name}<span class="sp-pv-ag"><span class="sp-pv-agi" role="img" aria-label={mk.label}>{@html mk.svg}</span>{r.provider}</span></span>
            <span class="sp-pv-line">{#if view.stamp}<span class="sp-pv-d">{view.stamp}</span>{/if}<span class:sp-dim={view.kind === 'none'}>{view.text}</span></span>
        </Button>
        <div class="sp-pv-foot">
            <span class="sp-pv-when">{age(r.s.last_activity_at)}</span>
            {#if action}
                <RowActionButton {action} {name} {t} onclick={() => onAct(action, r)} />
            {/if}
        </div>
    </div>
{/snippet}

{#snippet chips(list: readonly PageRow[], rid: string, cid: string)}
    {@const ck = keyOf(rid, cid)}
    {#each expanded[ck] ? list : list.slice(0, CAP) as r (r.s.session_uuid)}
        {@render chip(r, rid, cid)}
    {/each}
    {#if list.length > CAP}
        <Button variant="quiet" size="sm" data-more={ck} onclick={() => (expanded[ck] = !expanded[ck])}>{expanded[ck] ? t('sessions.page.pivot.fewer') : t('sessions.page.pivot.more', { n: list.length - CAP })}</Button>
    {/if}
{/snippet}

<div class="sp-pv" data-dens={dens}>
    <div class="sp-pv-axbar" role="group" aria-label={t('sessions.page.pivot.label')}>
        <label class="sp-pv-fld" data-g="rows">
            <span class="pl-label">{t('sessions.page.pivot.rows')}</span>
            <Select size="sm" aria-label={t('sessions.page.pivot.rows')} value={rAx} onchange={(e) => pickRows(e.currentTarget.value as AxisKey)} options={axisOptions} />
        </label>
        <Button size="sm" data-swap onclick={swap}>
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M2 5h11M10 2l3 3-3 3M14 11H3M6 8l-3 3 3 3" /></svg>
            <span>{t('sessions.page.pivot.swap')}</span>
        </Button>
        <label class="sp-pv-fld" data-g="cols">
            <span class="pl-label">{t('sessions.page.pivot.columns')}</span>
            <Select size="sm" aria-label={t('sessions.page.pivot.columns')} value={cAx} onchange={(e) => pickCols(e.currentTarget.value as AxisKey)} options={axisOptions} />
        </label>
        <Segmented data-g="dens" label={t('sessions.page.pivot.dens.label')} value={dens} onchange={(d) => setDens(d as Dens)}
            options={DENSITIES.map((d) => ({ value: d, label: t(`sessions.page.pivot.dens.${d}`), attrs: { 'data-dens': d } }))} />
        <div class="sp-pv-readout" aria-live="polite" data-readout>
            {#if hover}
                <b>{hover.name}</b> · {axisName(rAx)} {labelOf('r', hover.r)} · {axisName(cAx)} {labelOf('c', hover.c)}
                {#if iso}<Button size="sm" data-clear onclick={() => (iso = null)}>{t('sessions.page.pivot.clear_iso')}</Button>{/if}
            {:else if iso && slice}
                {t('sessions.page.pivot.isolated')} {axisName(iso.side === 'r' ? rAx : cAx)}: <b>{labelOf(iso.side, iso.id)}</b> · {sessionsOf(slice.n)} {t('sessions.page.pivot.across')} {nounOf(iso.side === 'r' ? cAx : rAx, slice.spans)}
                <Button size="sm" data-clear onclick={() => (iso = null)}>{t('sessions.page.pivot.clear')}</Button>
            {:else}
                {sessionsOf(rows.length)} · {nounOf(rAx, groupsShown)}{#if oldestDays}{' · '}{t('sessions.page.pivot.oldest', { d: oldestDays })}{/if}
            {/if}
        </div>
    </div>
    <div class="sp-sepbar" aria-hidden="true"></div>

    {#if phone}
        <div class="sp-pv-ph" data-ph>
            <div class="sp-pv-phcols" role="group" aria-label={t('sessions.page.pivot.phone.cols')}>
                {#each model.cols as c (c.id)}
                    <Button size="sm" data-ic={c.id} aria-pressed={iso !== null && iso.side === 'c' && iso.id === c.id} onclick={() => isolate('c', c.id)}>{c.short}<b>{model.colTally.get(c.id)?.n ?? 0}</b></Button>
                {/each}
            </div>
            {#each model.rows as r (r.id)}
                {#if !(iso && iso.side === 'r' && iso.id !== r.id)}
                    {@const sel = iso && iso.side === 'c' ? iso.id : phoneSel[r.id] !== undefined ? phoneSel[r.id] : (model.cols.find((c) => inCell(r.id, c.id).length)?.id ?? null)}
                    <section class="sp-pv-phsec" data-r={r.id}>
                        <div class="sp-pv-phhead">{@render head('r', r, model.rowTally.get(r.id), true)}</div>
                        <div class="sp-pv-phstrip" role="group" aria-label={r.label}>
                            {#each model.cols as c (c.id)}
                                {@const n = inCell(r.id, c.id).length}
                                <Button size="sm" data-pr={r.id} data-pc={c.id} aria-pressed={sel === c.id} disabled={n === 0} data-dim={iso && iso.side === 'c' && iso.id !== c.id ? '' : undefined} onclick={() => { if (iso?.side === 'c') iso = null; phoneSel[r.id] = phoneSel[r.id] === c.id ? null : c.id; }}>{c.short}<b>{n}</b></Button>
                            {/each}
                        </div>
                        {#if sel && inCell(r.id, sel).length}
                            <div class="sp-pv-phlist">
                                <div class="sp-pv-lh">{labelOf('c', sel)} · {sessionsOf(inCell(r.id, sel).length)}</div>
                                {@render chips(inCell(r.id, sel), r.id, sel)}
                            </div>
                        {/if}
                    </section>
                {/if}
            {/each}
        </div>
    {:else}
        <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
        <div class="sp-pv-scroll" bind:this={scroller} role="region" aria-label={t('sessions.page.pivot.scroll')} onkeydown={walk}>
            <div class="sp-pv-mx" role="grid" style:--cols={model.cols.length} style:--col-fit={fitW ? `${fitW}px` : undefined} data-fit={fitK || undefined}>
                <div class="sp-pv-corner"><span class="sp-pv-lab">{axisName(rAx)} {t('sessions.page.pivot.by')} {axisName(cAx)}</span></div>
                {#each model.cols as c (c.id)}
                    <div class="sp-pv-ch" role="columnheader" data-c={c.id} data-xh={hover?.c === c.id ? '' : undefined} class:sp-pv-dimhead={iso !== null && iso.side === 'c' && iso.id !== c.id}>
                        {@render head('c', c, model.colTally.get(c.id), false)}
                    </div>
                {/each}
                {#each shownRows as r (r.id)}
                    <div class="sp-pv-rh" role="rowheader" data-r={r.id} data-xh={hover?.r === r.id ? '' : undefined} class:sp-pv-dimhead={iso !== null && iso.side === 'r' && iso.id !== r.id}>
                        {@render head('r', r, model.rowTally.get(r.id), false)}
                    </div>
                    {#each model.cols as c (c.id)}
                        {@const list = inCell(r.id, c.id)}
                        <div class="sp-pv-cell" role="gridcell" data-r={r.id} data-c={c.id} data-n={list.length} data-xr={hover?.r === r.id ? '' : undefined} data-xc={hover?.c === c.id ? '' : undefined} data-dim={dimmed(r.id, c.id) ? '' : undefined}>
                            {@render chips(list, r.id, c.id)}
                        </div>
                    {/each}
                {/each}
                {#if foldedRows.length}
                    <div class="sp-pv-rh" data-r="_fold">
                        <Button variant="row" data-hb data-fold onclick={() => (fold = true)}>
                            <span class="sp-pv-t1"><span class="sp-pv-nm">{t('sessions.page.pivot.fold', { what: nounOf(rAx, foldedRows.length) })}</span></span>
                            <span class="sp-pv-t3">{t('sessions.page.pivot.fold.sub')}</span>
                        </Button>
                    </div>
                    {#each model.cols as c (c.id)}
                        <div class="sp-pv-cell" data-r="_fold" data-c={c.id}><span class="sp-pv-foldn">{foldedRows.reduce((n, r) => n + inCell(r.id, c.id).length, 0) || ''}</span></div>
                    {/each}
                {/if}
            </div>
        </div>
    {/if}
</div>
