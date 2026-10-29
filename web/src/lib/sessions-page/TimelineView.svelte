
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { visibilityObserver } from '../visibility-observer';
    import { ageFormatter } from '../projects-shared/format';
    import { motionReduced } from '../motion/motion';
    import { projectColorVar } from '../project-colors/palette';
    import { projectColorOf } from '../project-colors/store.svelte';
    import type { Translate } from '../sessions/types';
    import StatusLed from '../StatusLed.svelte';
    import Button from '../base/Button.svelte';
    import Checkbox from '../base/Checkbox.svelte';
    import Segmented from '../base/Segmented.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import { BookmarkWidgetActions } from '../../opscenter/cells/bookmarks/widget-actions.svelte';
    import type { PageRow } from './filters';
    import RowLed from './RowLed.svelte';
    import type { SessionsData } from './sessions-data.svelte';
    import { TimelineLanes } from './timeline-lanes.svelte';
    import { WINDOWS, laneColor, layoutLane, liveMoment, momentOf, planLanes, rulerTicks, type BookmarkTick, type LaneGroup, type Moment, type WindowKey } from './timeline-model';
    import './sessions-list.css';
    import './timeline.css';

    interface Props {
        rows: readonly PageRow[];
        data: SessionsData;
        t: Translate;
        now: () => number;
        selected?: string | null;
        onPreview: (sessionUuid: string | null) => void;
        lanes?: TimelineLanes;
    }
    const { rows, data, t, now, selected = null, onPreview, lanes = new TimelineLanes() }: Props = $props();

    const PHONE = '(max-width: 700px)';
    const isPhone = (): boolean => typeof matchMedia === 'function' && matchMedia(PHONE).matches;

    let windowMin = $state(isPhone() ? 360 : 1440);
    let m = $state(0);
    let clock = $state(now());
    let foldOpen = $state(false);
    let shut = $state<Record<string, boolean>>({});
    let hover = $state<string | null>(null);
    let trackW = $state(800);
    let rulerEl = $state<HTMLDivElement | undefined>();
    let innerEl = $state<HTMLDivElement | undefined>();
    let pending = $state<{ rowId: number; bookmarkId: number; label: string; name: string; running: boolean } | null>(null);
    const actions = new BookmarkWidgetActions();
    const age = $derived(ageFormatter(t, now));

    const windowKey = $derived(WINDOWS.find((w) => w.min === windowMin)?.key ?? '24h');
    const plan = $derived(planLanes(rows, data, windowMin, clock));
    const inGroups = (gs: readonly LaneGroup[]): PageRow[] => gs.flatMap((g) => [...g.rows]);
    const laneRows = $derived([...inGroups(plan.needs), ...inGroups(plan.running), ...inGroups(plan.asleep), ...(foldOpen ? inGroups(plan.fold) : [])]);
    const dense = $derived(laneRows.length > 45);
    const ticks = $derived(rulerTicks(clock, windowMin, trackW));
    const step = $derived(windowMin <= 60 ? 5 : 15);
    const count = (gs: readonly LaneGroup[]): number => gs.reduce((n, g) => n + g.rows.length, 0);
    const eligible = (r: PageRow): boolean => r.s.row_id !== null;
    const name = (r: PageRow): string => r.s.label ?? r.s.title;

    const groupIds = $derived([
        ...plan.needs.map((g) => `needs:${g.key}`),
        ...plan.running.map((g) => `running:${g.key}`),
        ...plan.asleep.map((g) => `asleep:${g.key}`),
        ...(foldOpen ? plan.fold.map((g) => `fold:${g.key}`) : []),
    ]);

    export function allExpanded(): boolean {
        return groupIds.length > 0 && groupIds.every((id) => !shut[id]);
    }

    export function toggleAll(): void {
        const fold = allExpanded();
        for (const id of groupIds) shut[id] = fold;
    }

    const at = (minutes: number): number => ((windowMin - minutes) / windowMin) * 100;
    const px = (x: number): string => `${x.toFixed(3)}%`;

    function momentFor(r: PageRow): Moment | ReturnType<typeof liveMoment> {
        if (m <= 0) return liveMoment(r.s.state !== 'running', data.asleepUnread(r.s.session_uuid), data.live(r.s));
        return momentOf(lanes.lanes[r.s.session_uuid]?.tl ?? null, m, clock);
    }

    const tally = $derived.by(() => {
        const c = { working: 0, waiting: 0, quiet: 0, unknown: 0, dead: 0, asleep: 0 };
        for (const r of rows) c[momentFor(r).cat] += 1;
        const lanesNeeded = laneRows.filter(eligible);
        const read = lanesNeeded.filter((r) => lanes.lanes[r.s.session_uuid]?.status === 'ready' || lanes.lanes[r.s.session_uuid]?.tl).length;
        return { c, read, of: lanesNeeded.length };
    });
    const COUNT_ORDER = ['working', 'waiting', 'quiet', 'unknown', 'dead', 'asleep'] as const;
    const COUNT_LED: Record<(typeof COUNT_ORDER)[number], string> = { working: 'working', waiting: 'question', quiet: 'idle', unknown: 'unknown', dead: 'dead', asleep: 'asleep' };

    function momentText(ms: number): string {
        const d = new Date(ms);
        const days = Math.round((new Date(clock).setHours(0, 0, 0, 0) - new Date(ms).setHours(0, 0, 0, 0)) / 86400000);
        const day = days === 0 ? t('sessions.page.tl.today') : days === 1 ? t('sessions.page.tl.yesterday') : d.toLocaleDateString('en-US', { weekday: 'short' }).toLowerCase();
        return `${day} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    }

    function dur(minutes: number): string {
        const v = Math.round(minutes);
        if (v < 60) return `${v}m`;
        if (v < 1440) return `${Math.floor(v / 60)}h${v % 60 ? ` ${v % 60}m` : ''}`;
        return `${Math.floor(v / 1440)}d${Math.floor((v % 1440) / 60) ? ` ${Math.floor((v % 1440) / 60)}h` : ''}`;
    }

    const statusWord = (mo: Moment | ReturnType<typeof liveMoment>): string => t(`sessions.page.state.${mo.status}`);

    function timerMinutes(r: PageRow): number | null {
        const fire = data.live(r.s)?.timers_next_fire_at;
        if (!fire || r.s.state !== 'running') return null;
        const minutes = Math.round((Date.parse(fire) - clock) / 60000);
        return minutes > 0 ? minutes : null;
    }

    const detailRow = $derived(rows.find((r) => r.s.session_uuid === (hover ?? selected)) ?? null);

    function setPlayhead(minutes: number): void {
        m = Math.max(0, Math.min(windowMin, Math.round(minutes)));
    }

    function posToMinutes(x: number): number {
        const r = rulerEl?.getBoundingClientRect();
        if (!r || r.width === 0) return m;
        const f = Math.max(0, Math.min(1, (x - r.left) / r.width));
        const grain = windowMin <= 360 ? 1 : windowMin <= 1440 ? 5 : 30;
        return Math.round(((1 - f) * windowMin) / grain) * grain;
    }

    let dragging = false;
    function startDrag(e: PointerEvent): void {
        if (isPhone() || e.button !== 0 || (e.target as HTMLElement).closest('button')) return;
        dragging = true;
        e.preventDefault();
        setPlayhead(posToMinutes(e.clientX));
        const move = (ev: PointerEvent): void => setPlayhead(posToMinutes(ev.clientX));
        const up = (): void => {
            dragging = false;
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', up);
            window.removeEventListener('pointercancel', up);
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
        window.addEventListener('pointercancel', up);
    }

    function rulerKey(e: KeyboardEvent): void {
        const d = e.shiftKey ? 60 : step;
        if (e.key === 'ArrowLeft') setPlayhead(m + d);
        else if (e.key === 'ArrowRight') setPlayhead(m - d);
        else if (e.key === 'Home') setPlayhead(windowMin);
        else if (e.key !== 'End') return;
        else setPlayhead(0);
        e.preventDefault();
    }

    function pageKey(e: KeyboardEvent): void {
        const target = e.target as HTMLElement | null;
        if (e.key !== 'n' || e.metaKey || e.ctrlKey || e.altKey || (target && (/^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName) || target.isContentEditable))) return;
        setPlayhead(0);
    }

    function setWindow(minutes: number): void {
        windowMin = minutes;
        if (m > minutes) m = minutes;
    }

    function pickMark(r: PageRow, mark: BookmarkTick): void {
        actions.armed = false;
        pending = { rowId: r.s.row_id ?? 0, bookmarkId: mark.bookmarkId, label: mark.label || t('bookmarks.by_claude'), name: name(r), running: r.s.state === 'running' };
    }

    async function rewind(): Promise<void> {
        if (!pending) return;
        await actions.rewind(pending.rowId, { bookmarkId: pending.bookmarkId });
        if (actions.notice && !actions.notice.error) pending = null;
    }

    function laneClick(e: MouseEvent, r: PageRow): void {
        const target = e.target as HTMLElement;
        if (target.closest('.sp-tl-bk')) return;
        if (target.closest('.sp-tl-track') && !target.closest('.sp-tl-cv')) return;
        onPreview(selected === r.s.session_uuid ? null : r.s.session_uuid);
    }

    function laneKey(e: KeyboardEvent, r: PageRow): void {
        if ((e.key === 'Enter' || e.key === ' ') && e.target === e.currentTarget) {
            e.preventDefault();
            onPreview(selected === r.s.session_uuid ? null : r.s.session_uuid);
        }
    }

    function onscreen(node: HTMLElement, param: { uuid: string; rowId: number | null }) {
        if (param.rowId === null) return {};
        lanes.know(param.uuid, param.rowId);
        const Observer = visibilityObserver();
        if (!Observer) {
            lanes.show(param.uuid, true);
            return { destroy: () => lanes.show(param.uuid, false) };
        }
        const io = new Observer((entries) => entries.forEach((en) => lanes.show(param.uuid, en.isIntersecting)), { rootMargin: '200px' });
        io.observe(node);
        return {
            destroy: () => {
                io.disconnect();
                lanes.show(param.uuid, false);
            },
        };
    }

    async function minuteTick(): Promise<void> {
        if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
        clock = now();
        if (m > 0) m = Math.min(windowMin, m + 1);
        if (!innerEl || motionReduced()) return;
        const slide = (trackW / windowMin).toFixed(2);
        innerEl.removeAttribute('data-slide');
        innerEl.style.transform = `translateX(${slide}px)`;
        await tick();
        void innerEl.offsetWidth;
        innerEl.setAttribute('data-slide', '');
        innerEl.style.transform = 'none';
    }

    onMount(() => {
        lanes.start();
        const timer = setInterval(() => void minuteTick(), 60000);
        return () => {
            clearInterval(timer);
            lanes.stop();
        };
    });
</script>

<svelte:window onkeydown={pageKey} />

{#snippet groupHead(g: LaneGroup, n: string, id: string)}
    {@const pc = laneColor(g.projectRef, projectColorOf)}
    <Button variant="row" data-tl-grp aria-expanded={!shut[id]} data-block={pc && shut[id] ? '' : undefined} style={pc ? `--sp-block: ${pc}` : undefined} onclick={() => (shut[id] = !shut[id])}>
        <span class="sp-tl-car">{shut[id] ? '>' : 'v'}</span>
        <span class="sp-pchip" style:--pc={projectColorVar(projectColorOf(g.projectRef?.id ?? null))}>{(g.project.charAt(0) || '?').toUpperCase()}</span>
        <b>{g.project}</b>
        <span>{n}</span>
    </Button>
{/snippet}

{#snippet lane(r: PageRow, quiet: boolean, pc?: string)}
    {@const uuid = r.s.session_uuid}
    {@const read = lanes.lanes[uuid]}
    {@const d = layoutLane(read?.tl ?? null, windowMin, clock)}
    {@const mo = momentFor(r)}
    {@const timer = timerMinutes(r)}
    <div
        class="sp-tl-lane"
        role="group"
        aria-label={t('sessions.page.tl.lane', { name: name(r) })}
        tabindex="0"
        data-uuid={uuid}
        data-state={r.s.state}
        data-pc={pc ? '' : undefined}
        style:--tl-busy={pc}
        aria-selected={selected === uuid ? 'true' : undefined}
        use:onscreen={{ uuid, rowId: quiet ? null : r.s.row_id }}
        onclick={(e) => laneClick(e, r)}
        onkeydown={(e) => laneKey(e, r)}
        onpointerenter={(e) => e.pointerType !== 'touch' && (hover = uuid)}
        onpointerleave={() => (hover = null)}
        onfocusin={() => (hover = uuid)}
        onfocusout={() => (hover = null)}
    >
        <div class="sp-tl-name">
            <span class="sp-tl-led"><SessionFace bare row={{ status: mo.status, unread: mo.unread }} /></span>
            <span class="sp-tl-nm">{name(r)}</span>
            {#if r.s.host_label}<span class="sp-tl-hostl">{r.s.host_label}</span>{/if}
            <span class="sp-tl-age">{age(r.s.last_activity_at)}</span>
        </div>
        <div class="sp-tl-track" onpointerdown={startDrag}>
            {#if r.s.state === 'running'}<i class="sp-tl-base"></i>{/if}
            {#if quiet}
                <span class="sp-tl-qt">{t('sessions.page.tl.asleep_ago', { age: age(r.s.last_activity_at) })}</span>
            {:else if !eligible(r)}
                <span class="sp-tl-qt">{t('sessions.page.state.unknown')}</span>
            {:else if read?.status === 'error' && !read.tl}
                <div class="sp-tl-fail"><span>{t('sessions.page.tl.unavailable')}</span></div>
            {:else}
                {#each d.sleeps as s (s.x0)}<span class="sp-tl-moon" style:left={px(s.x0)}><StatusLed status="asleep" size="8px" /></span>{/each}
                {#if d.span}
                    {@const span = d.span}
                    <button type="button" class="sp-tl-cv" style:left={px(span.x0)} style:width={px(span.x1 - span.x0)} aria-label={t('sessions.page.tl.open', { name: name(r) })}>
                        {#if span.x0 > 0}<i class="sp-tl-cap" data-end="l"></i>{/if}
                        {#if span.x1 < 100}<i class="sp-tl-cap" data-end="r"></i>{/if}
                        {#each d.busy as b (b.x0)}<i class="sp-tl-bd" style:left={px(((b.x0 - span.x0) / (span.x1 - span.x0)) * 100)} style:width={px(((b.x1 - b.x0) / (span.x1 - span.x0)) * 100)}></i>{/each}
                    </button>
                {/if}
                {#each d.waits as w (`${w.kind}${w.x0}`)}<i class="sp-tl-wt" data-kind={w.kind} style:left={px(w.x0)} style:width={px(w.x1 - w.x0)}></i>{/each}
                {#each d.marks as k (k.bookmarkId)}
                    <button type="button" class="sp-tl-bk" style:left={px(k.x)} aria-pressed={pending?.bookmarkId === k.bookmarkId} aria-label={t('sessions.page.tl.mark', { at: momentText(Date.parse(k.at)) })} onclick={() => pickMark(r, k)}></button>
                {/each}
            {/if}
        </div>
        <div class="sp-tl-stub">
            <span class="sp-tl-stubed"><RowLed row={r} live={data.live(r.s)} asleepUnread={data.asleepUnread(uuid)} /></span>
            {#if timer !== null}
                <span class="sp-tl-timer" title={t('sessions.page.tl.timer', { n: String(timer) })}><i style:width="{Math.round(Math.min(1, timer / 60) * 38)}px"></i><span>{t('sessions.page.tl.timer_n', { n: String(timer) })}</span></span>
            {/if}
        </div>
    </div>
{/snippet}

<div class="sp-tl" role="presentation">
    <div class="sp-tl-stick">
        <div class="sp-tl-ctl">
            <Segmented label={t('sessions.page.tl.window.label')} value={windowKey} onchange={(key) => setWindow(WINDOWS.find((w) => w.key === key)?.min ?? windowMin)}
                options={WINDOWS.map((w) => ({ value: w.key, label: t(`sessions.page.tl.window.${w.key}`), attrs: { 'data-w': w.key } }))} />
        </div>
        <div class="sp-sepbar" aria-hidden="true"></div>
        <div class="sp-tl-readout" aria-live="polite">
            <div class="sp-tl-moment">
                {m <= 0 ? t('sessions.page.tl.now') : momentText(clock - m * 60000)}
                {#if m > 0}<small>{t('sessions.page.tl.before', { dur: dur(m) })}</small>{/if}
            </div>
            <div class="sp-tl-rmain">
                <div class="sp-tl-counts">
                    {#each COUNT_ORDER as k (k)}
                        {#if k !== 'dead' || tally.c.dead > 0}
                            <span><StatusLed bare status={COUNT_LED[k]} /> <b>{tally.c[k]}</b> {t(`sessions.page.tl.count.${k}`)}</span>
                        {/if}
                    {/each}
                </div>
                <div class="sp-tl-detail">
                    {#if pending}
                        <span class="sp-tl-rw" data-tl-rewind>
                            <span>{t('sessions.page.tl.rewind.to', { name: pending.name, label: pending.label })}</span>
                            <span class="sp-tl-arm" title={pending.running ? undefined : t('bookmarks.arm_not_live')}>
                                <Checkbox tone="danger" label={t('bookmarks.arm')} bind:checked={actions.armed} disabled={!pending.running} />
                            </span>
                            <Button size="sm" variant="danger" data-tl-act="rewind" disabled={!pending.running || !actions.armed || actions.busy !== null} onclick={() => void rewind()}>{t('sessions.page.tl.rewind.go')}</Button>
                            <Button size="sm" data-tl-act="cancel" onclick={() => (pending = null)}>{t('sessions.page.tl.rewind.cancel')}</Button>
                        </span>
                    {:else if actions.notice}
                        <span class="sp-tl-note" role="status" data-error={actions.notice.error ? '' : undefined}>{actions.notice.text}</span>
                    {:else if detailRow}
                        {@const mo = momentFor(detailRow)}
                        {@const nowMo = liveMoment(detailRow.s.state !== 'running', data.asleepUnread(detailRow.s.session_uuid), data.live(detailRow.s))}
                        {@const tm = timerMinutes(detailRow)}
                        <em>{name(detailRow)}</em> · {detailRow.project}{detailRow.company ? ` (${detailRow.company})` : ''} · {m > 0 ? t('sessions.page.tl.detail.at', { moment: momentText(clock - m * 60000), state: statusWord(mo) }) : statusWord(mo)}{#if m > 0 && nowMo.status !== mo.status} · {t('sessions.page.tl.detail.now', { state: statusWord(nowMo) })}{/if}{#if tm !== null} · {t('sessions.page.tl.timer', { n: String(tm) })}{/if}
                    {:else if m > 0 && tally.read < tally.of}
                        {t('sessions.page.tl.read', { n: String(tally.read), total: String(tally.of) })}
                    {/if}
                </div>
            </div>
            <div class="sp-tl-ract">
                {#if m > 0}<Button size="sm" data-tl-now onclick={() => setPlayhead(0)}>{t('sessions.page.tl.now')}</Button>{/if}
            </div>
        </div>
        <div class="sp-tl-key" role="group" aria-label={t('sessions.page.tl.key.label')}>
            <span class="sp-tl-keyh">{t('sessions.page.tl.key.label')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-bd"></i>{t('sessions.page.tl.key.working')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-kline"></i>{t('sessions.page.tl.key.trace')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-wt" data-kind="question"></i>{t('sessions.page.tl.key.question')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-wt" data-kind="notice"></i>{t('sessions.page.tl.key.notice')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-wt" data-kind="done"></i>{t('sessions.page.tl.key.done')}</span>
            <span class="sp-tl-ks"><span class="sp-tl-moon"><StatusLed status="asleep" size="8px" /></span>{t('sessions.page.tl.key.asleep')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-bk"></i>{t('sessions.page.tl.key.bookmark')}</span>
            <span class="sp-tl-ks"><i class="sp-tl-base"></i>{t('sessions.page.tl.key.running')}</span>
            <span class="sp-tl-ks"><StatusLed bare status="working" />{t('sessions.page.tl.key.now')}</span>
        </div>
        <div class="sp-tl-ruler">
            <div class="sp-tl-rlabel">{t('sessions.page.tl.ruler.label', { window: windowKey })}</div>
            <div
                class="sp-tl-rtrack"
                bind:this={rulerEl}
                bind:clientWidth={trackW}
                role="slider"
                tabindex="0"
                aria-label={t('sessions.page.tl.ruler.aria', { n: String(step) })}
                aria-valuemin={0}
                aria-valuemax={windowMin}
                aria-valuenow={windowMin - m}
                aria-valuetext={m <= 0 ? t('sessions.page.tl.now') : momentText(clock - m * 60000)}
                onpointerdown={startDrag}
                onkeydown={rulerKey}
            >
                {#each ticks as k (`${k.m}${k.major}`)}
                    <i class="sp-tl-tk" data-major={k.major ? '' : undefined} style:left={px(at(k.m))}></i>
                    {#if k.label}<span class="sp-tl-tl" style:left={px(at(k.m))}>{k.label}</span>{/if}
                {/each}
                <span class="sp-tl-tl sp-tl-nowl">{t('sessions.page.tl.now')}</span>
                <i class="sp-tl-handle" style:left={px(at(m))}></i>
            </div>
            <div></div>
        </div>
    </div>
    <div class="sp-tl-lanes" data-dense={dense ? '' : undefined}>
        <div class="sp-tl-inner" bind:this={innerEl}>
            <div class="sp-tl-over" aria-hidden="true">
                {#each ticks as k (`${k.m}${k.major}`)}{#if k.major}<i class="sp-tl-gl" style:left={px(at(k.m))}></i>{/if}{/each}
                <i class="sp-tl-edge"></i>
                {#if m > 0}<i class="sp-tl-ph" style:left={px(at(m))}></i>{/if}
            </div>
            <div role="list">
                {#snippet groups(gs: readonly LaneGroup[], quiet: boolean, n: (g: LaneGroup) => string, sec: string)}
                    {#each gs as g (g.key)}
                        {@const pc = laneColor(g.projectRef, projectColorOf)}
                        {@const id = `${sec}:${g.key}`}
                        <div class="sp-tl-gbox" data-block={pc && !shut[id] ? '' : undefined} style:--sp-block={pc}>
                            {@render groupHead(g, n(g), id)}
                            {#if !shut[id]}{#each g.rows as r (r.s.session_uuid)}{@render lane(r, quiet, pc)}{/each}{/if}
                        </div>
                    {/each}
                {/snippet}
                {#if plan.needs.length}
                    <div class="sp-tl-sec"><span>{t('sessions.page.tl.sec.needs')}</span><span>{count(plan.needs)}</span></div>
                    {@render groups(plan.needs, false, (g) => String(g.rows.length), 'needs')}
                {/if}
                {#if plan.running.length}
                    <div class="sp-tl-sec"><span>{t('sessions.page.tl.sec.running')}</span><span>{count(plan.running)}</span></div>
                    {@render groups(plan.running, false, (g) => String(g.rows.length), 'running')}
                {/if}
                {#if plan.asleep.length}
                    <div class="sp-tl-sec"><span>{t('sessions.page.tl.sec.asleep', { window: windowKey })}</span><span>{count(plan.asleep)}</span></div>
                    {@render groups(plan.asleep, false, (g) => t('sessions.page.tl.asleep_n', { n: String(g.rows.length) }), 'asleep')}
                {/if}
                {#if plan.fold.length}
                    <Button variant="row" data-tl-fold aria-expanded={foldOpen} onclick={() => (foldOpen = !foldOpen)}>
                        <span class="sp-tl-car">{foldOpen ? 'v' : '>'}</span><span>{t('sessions.page.tl.fold', { n: String(count(plan.fold)), window: windowKey })}</span>
                    </Button>
                    {#if foldOpen}{@render groups(plan.fold, true, (g) => t('sessions.page.tl.asleep_n', { n: String(g.rows.length) }), 'fold')}{/if}
                {/if}
                {#if rows.length === 0}<div class="sp-tl-empty">{t('sessions.page.tl.empty')}</div>{/if}
            </div>
        </div>
    </div>
    <div class="sp-tl-slider">
        <input class="sp-tl-range" type="range" min="0" max={windowMin} step="1" value={windowMin - m} aria-label={t('sessions.page.tl.slider')} oninput={(e) => setPlayhead(windowMin - Number(e.currentTarget.value))} />
    </div>
</div>
