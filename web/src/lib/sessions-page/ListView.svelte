
<script lang="ts">
    import { animationTypeOff } from '../motion/animation-types';
    import { forwardMenuKey } from '../item-menu/page-row';
    import { onMount, tick, type Snippet } from 'svelte';
    import { ageFormatter } from '../projects-shared/format';
    import type { Translate } from '../sessions/types';
    import type { HistoryProject } from '../projects-shared/history-api';
    import type { PageRow } from './filters';
    import { archivedBand, projectBands } from './inactive-projects';
    import { ARCHIVED_FOLD_KEY, companyFoldKey, projectFoldKey, storedFold, storeFolds } from './folds';
    import { COMPANY_GROUP_PREFIX, companyLayout } from './company-layout';
    import { companies, type Company } from '../companies';
    import type { ProjectSortKey } from './toolbar-prefs';
    import List from '../base/List.svelte';
    import State from '../base/State.svelte';
    import ClosedRows from './ClosedRows.svelte';
    import { closedByKey, closedOnlyGroups, historyKeyOf } from './closed-model';
    import GroupSection from './GroupSection.svelte';
    import { LENSES, lensGroups, type LensGroup, lensMeasure, readLens, writeLens, type LensContext, type LensKey } from './lenses';
    import LensRail from './LensRail.svelte';
    import ListHead from './ListHead.svelte';
    import { latestView } from './latest-line';
    import { pinnedUuidSet } from './pins';
    import { rowAction, type RowAction } from './row-action';
    import SessionLine from './SessionLine.svelte';
    import type { SessionsData } from './sessions-data.svelte';
    import { nextSort, sortGroups, type ColumnKey, type SortState } from './sorting';
    import { OPEN_DELAY_MS, TypeAhead } from './typeahead';
    import './sessions-list.css';

    interface Props {
        rows: readonly PageRow[];
        data: SessionsData;
        t: Translate;
        now: () => number;
        searching: boolean;
        active?: boolean;
        selected?: string | null;
        previewing?: boolean;
        onPreview?: (sessionUuid: string | null) => void;
        onAct: (kind: RowAction, row: PageRow) => void;
        emptyProjects?: readonly HistoryProject[];
        find?: string;
        withEmpties?: boolean;
        showArchived?: boolean;
        projectSort?: ProjectSortKey;
        onProjectAction?: (id: string, group: LensGroup) => void;
        onCompanyAction?: (id: string, company: Company) => void;
        projectBusy?: boolean;
        closedRows?: readonly PageRow[];
        busyIds?: ReadonlySet<string>;
        bar?: Snippet;
    }
    let { rows, data, t, now, searching, active = true, selected = $bindable(null), previewing = false, onPreview, onAct, emptyProjects = [], find = '', withEmpties = true, showArchived = false, projectSort = 'default', onProjectAction, onCompanyAction, projectBusy = false, closedRows = [], busyIds = new Set<string>(), bar }: Props = $props();

    let lens = $state<LensKey>(readLens());
    let sort = $state<SortState | null>(null);
    let folded = $state<Record<string, boolean>>({});
    let foldTick = $state(0);
    let current = $state<string | null>(null);
    let listEl = $state<HTMLDivElement | undefined>();
    let selbox = $state<HTMLDivElement | undefined>();
    let rootEl = $state<HTMLDivElement | undefined>();
    const ta = new TypeAhead();
    let openTimer: ReturnType<typeof setTimeout> | undefined;

    const pinnedUuids = $derived.by((): ReadonlySet<string> => {
        void data.pinTick;
        return pinnedUuidSet();
    });

    const ctx = $derived<LensContext>({
        t,
        now: now(),
        sig: data,
        isPinned: (r) => pinnedUuids.has(r.s.session_uuid),
        usage: data.usage,
        conversations: data.conversations,
        age: ageFormatter(t, now),
        latest: (r) => latestView(r.s, data.latest[r.s.session_uuid], now(), t).text,
        noCompany: t('sessions.page.filter.no_company'),
        thisComputer: t('sessions.page.filter.this_computer'),
    });

    const listingDown = $derived(data.listingDown);
    const bands = $derived.by(() => {
        const sorted = sortGroups(lensGroups(lens, rows, ctx), sort, lens, ctx);
        return lens === 'project' ? projectBands(sorted, emptyProjects, find, withEmpties, projectSort) : { groups: sorted, inactive: new Set<string>() };
    });
    const layout = $derived(lens === 'project' ? companyLayout(bands.groups, companies.list, find, withEmpties, t) : null);
    const groups = $derived(layout ? layout.groups : bands.groups);
    const closedBy = $derived(lens === 'project' ? closedByKey(closedRows) : new Map<string, PageRow[]>());
    const closedOnly = $derived(closedOnlyGroups(closedBy, new Set(groups.map(historyKeyOf))));
    const age = $derived(ageFormatter(t, now));

    function selectClosed(r: PageRow): void {
        const id = r.s.session_uuid;
        if (previewing && selected === id) onPreview?.(null);
        else {
            selected = id;
            onPreview?.(id);
        }
    }
    const archivedGroups = $derived(lens === 'project' ? archivedBand(data.archivedProjects, find, withEmpties && showArchived) : []);
    const archivedHead = $derived<LensGroup>({ key: 'archived', label: t('sessions.page.group.archived'), bits: [t('sessions.page.group.archived_n', { n: archivedGroups.length })], measure: '', rows: [], count: archivedGroups.length, live: 0, project: null, provider: null });
    const counts = $derived(
        Object.fromEntries(LENSES.map((l) => [l.key, l.key === 'needs' && listingDown ? 0 : lensGroups(l.key, rows, ctx).reduce((n, g) => n + g.count, 0)])) as Record<LensKey, number>,
    );

    function storeKeyOf(key: string): string | null {
        if (lens !== 'project') return null;
        if (key.startsWith(COMPANY_GROUP_PREFIX)) return companyFoldKey(Number(key.slice(COMPANY_GROUP_PREFIX.length)));
        return key === 'archived' ? ARCHIVED_FOLD_KEY : projectFoldKey(groups.find((g) => g.key === key)?.project?.id);
    }

    function isFolded(key: string, index: number): boolean {
        const inactive = bands.inactive.has(key) || key === 'archived';
        const company = key.startsWith(COMPANY_GROUP_PREFIX);
        if (searching && !inactive) return false;
        const sk = storeKeyOf(key);
        if (sk) {
            void data.pinTick;
            void foldTick;
            const chosen = storedFold(sk);
            if (chosen !== null) return chosen;
        } else {
            const k = `${lens}|${key}`;
            if (k in folded) return folded[k] as boolean;
        }
        return !company && (inactive || (rows.length > 120 && index >= 3));
    }

    function setFolds(choices: ReadonlyArray<readonly [string, boolean]>): void {
        const stored: Array<readonly [string, boolean]> = [];
        for (const [key, on] of choices) {
            const sk = storeKeyOf(key);
            if (sk) stored.push([sk, on]);
            else folded[`${lens}|${key}`] = on;
        }
        if (!stored.length) return;
        storeFolds(stored);
        foldTick += 1;
    }

    function rowEls(): HTMLElement[] {
        return listEl ? [...listEl.querySelectorAll<HTMLElement>('.sp-row[data-id]')] : [];
    }

    function elOf(id: string | null): HTMLElement | undefined {
        return id ? rowEls().find((el) => el.dataset.id === id) : undefined;
    }

    function headH(): number {
        return listEl?.querySelector<HTMLElement>('.sp-lhead')?.offsetHeight ?? 0;
    }

    function ensureVisible(el: HTMLElement): void {
        if (!listEl) return;
        const top = el.offsetTop;
        const bottom = top + el.offsetHeight;
        const clear = 40 + headH();
        if (top - clear < listEl.scrollTop) listEl.scrollTop = Math.max(0, top - clear);
        else if (bottom > listEl.scrollTop + listEl.clientHeight - 8) listEl.scrollTop = bottom - listEl.clientHeight + 8;
    }

    async function openGroup(key: string): Promise<void> {
        const at = groups.findIndex((g) => g.key === key);
        const g = groups[at];
        if (!g) return;
        const shut = [g.key, ...(layout?.sections.filter((s) => s.groups.includes(g)).map((s) => s.head.key) ?? [])].filter((k) => isFolded(k, k === g.key ? at : -1));
        if (shut.length) {
            setFolds(shut.map((k) => [k, false] as const));
            await tick();
        }
    }

    async function reveal(id: string): Promise<void> {
        const g = groups.find((x) => x.rows.some((r) => r.s.session_uuid === id));
        if (g) await openGroup(g.key);
    }

    async function choose(id: string, opts: { open?: boolean; focus?: boolean } = {}): Promise<void> {
        await reveal(id);
        selected = id;
        const el = elOf(id);
        if (el) {
            current = el.closest<HTMLElement>('.sp-sec')?.dataset.key ?? null;
            ensureVisible(el);
        }
        if (opts.open || previewing) onPreview?.(id);
        if (opts.focus !== false) listEl?.focus({ preventScroll: true });
    }

    function nav(d: 1 | -1): void {
        const els = rowEls();
        if (!els.length) return;
        const i = els.findIndex((e) => e.dataset.id === selected);
        const el = i < 0 ? (d > 0 ? els[0] : els[els.length - 1]) : els[Math.max(0, Math.min(els.length - 1, i + d))];
        if (el?.dataset.id) void choose(el.dataset.id);
    }

    function selectedRow(): PageRow | undefined {
        return rows.find((r) => r.s.session_uuid === selected);
    }

    function actSelected(): void {
        const r = selectedRow();
        const kind = r ? rowAction(r.s) : null;
        if (r && kind) onAct(kind, r);
    }

    function foldSelected(on: boolean): void {
        if (searching || !current) return;
        setFolds([[current, on]]);
        void tick().then(() => placeSel(true));
        if (!on && selected) void tick().then(() => selected && void choose(selected, { focus: false }));
    }

    function jump(prefix: string): boolean {
        const hit = groups.flatMap((g) => g.rows).find((r) => (r.s.label ?? r.s.title).toLowerCase().startsWith(prefix));
        if (hit) void choose(hit.s.session_uuid);
        return Boolean(hit);
    }

    function typeKey(ch: string): void {
        const act = ta.press(ch, Date.now(), (p) => groups.some((g) => g.rows.some((r) => (r.s.label ?? r.s.title).toLowerCase().startsWith(p))));
        clearTimeout(openTimer);
        if (act.type === 'next') nav(1);
        else if (act.type === 'prev') nav(-1);
        else if (act.type === 'open-soon') openTimer = setTimeout(() => ta.commandOnly && actSelected(), OPEN_DELAY_MS);
        else if (act.type === 'panel') togglePanel();
        else if (act.type === 'jump') jump(act.prefix);
    }

    function togglePanel(): void {
        if (!selected) return;
        if (previewing) onPreview?.(null);
        else void choose(selected, { open: true });
    }

    function onKey(e: KeyboardEvent): void {
        if (!active || e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
        const target = e.target instanceof HTMLElement ? e.target : null;
        if (!target) return;
        if (/^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName) || target.isContentEditable) return;
        const page = rootEl?.closest('.sp-page');
        if (target !== document.body && !(page && page.contains(target))) return;
        if (target.closest('.sp-rail, .sp-bar, .sp-lhead')) return;
        if (target.tagName === 'BUTTON' && (e.key === 'Enter' || e.key === ' ')) return;
        if (e.key === 'ArrowDown') nav(1);
        else if (e.key === 'ArrowUp') nav(-1);
        else if (e.key === 'Enter') actSelected();
        else if (forwardMenuKey(e, elOf(selected) ?? null)) {  }
        else if (e.key === 'ArrowLeft') foldSelected(true);
        else if (e.key === 'ArrowRight') foldSelected(false);
        else if (e.key.length === 1 && /[a-z0-9\- .]/i.test(e.key)) typeKey(e.key);
        else return;
        e.preventDefault();
    }

    $effect(() => {
        window.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('keydown', onKey);
            clearTimeout(openTimer);
        };
    });

    function stillPlease(): boolean {
        return animationTypeOff('layout-moves') || (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    function placeSel(instant: boolean): void {
        if (!selbox) return;
        const el = elOf(selected);
        if (!el || !el.offsetParent) {
            selbox.hidden = true;
            return;
        }
        const jump = instant || selbox.hidden || stillPlease();
        selbox.hidden = false;
        if (jump) selbox.classList.add('sp-selbox--instant');
        selbox.style.height = `${el.offsetHeight}px`;
        selbox.style.left = `${el.offsetLeft}px`;
        selbox.style.width = `${el.offsetWidth}px`;
        selbox.style.transform = `translateY(${el.offsetTop}px)`;
        if (jump) {
            void selbox.offsetWidth;
            selbox.classList.remove('sp-selbox--instant');
        }
    }

    $effect(() => {
        void selected;
        void tick().then(() => placeSel(false));
    });

    let tops: Record<string, number> = {};
    let topsLens: LensKey | null = null;

    $effect.pre(() => {
        void groups;
        if (!listEl || !listEl.offsetParent) {
            tops = {};
            return;
        }
        tops = Object.fromEntries(rowEls().map((el) => [el.dataset.id ?? '', el.getBoundingClientRect().top]));
        topsLens = lens;
    });

    function slideRows(): void {
        const before = tops;
        tops = {};
        if (stillPlease() || topsLens !== lens || !listEl) return;
        for (const el of rowEls()) {
            const was = before[el.dataset.id ?? ''];
            if (was === undefined || typeof el.animate !== 'function') continue;
            const dy = was - el.getBoundingClientRect().top;
            if (Math.abs(dy) > 2 && Math.abs(dy) < 4000) el.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }], { duration: 200, easing: 'ease-out' });
        }
    }

    function setLens(key: LensKey): void {
        lens = key;
        writeLens(key);
        current = null;
        if (listEl) listEl.scrollTop = 0;
    }

    function toggleFold(key: string, index: number): void {
        if (searching && !bands.inactive.has(key) && key !== 'archived') return;
        setFolds([[key, !isFolded(key, index)]]);
        void tick().then(() => placeSel(true));
    }

    async function goSection(key: string): Promise<void> {
        const at = groups.findIndex((g) => g.key === key);
        if (at < 0) return;
        await openGroup(key);
        const sec = [...(listEl?.querySelectorAll<HTMLElement>('.sp-sec') ?? [])].find((el) => el.dataset.key === key);
        if (sec && listEl) {
            listEl.scrollTop = sec.offsetTop - headH();
            spy();
        }
    }

    function spy(): void {
        if (!listEl) return;
        const top = listEl.scrollTop + 48 + headH();
        let cur: string | null = null;
        for (const s of listEl.querySelectorAll<HTMLElement>('.sp-sec')) if (s.offsetTop <= top) cur = s.dataset.key ?? null;
        current = cur;
    }

    let spyQueued = false;
    function onScroll(): void {
        if (spyQueued) return;
        spyQueued = true;
        requestAnimationFrame(() => {
            spyQueued = false;
            spy();
        });
    }

    async function onSort(k: ColumnKey | null): Promise<void> {
        sort = k ? nextSort(sort, k) : null;
        if (!k) return;
        await tick();
        listEl?.querySelector<HTMLElement>(`.sp-hc[data-sort="${k}"]`)?.focus({ preventScroll: true });
    }

    function onReverse(): void {
        if (sort) sort = { k: sort.k, dir: sort.dir === 1 ? -1 : 1 };
    }

    function onSelect(r: PageRow): void {
        const id = r.s.session_uuid;
        if (previewing && selected === id) {
            onPreview?.(null);
            listEl?.focus({ preventScroll: true });
        } else void choose(id, { open: true });
    }

    function padEnd(): void {
        if (!listEl) return;
        const secs = listEl.querySelectorAll<HTMLElement>('.sp-sec');
        const last = secs[secs.length - 1];
        listEl.style.paddingBottom = last ? `${Math.max(24, listEl.clientHeight - last.offsetHeight - 24)}px` : '';
    }

    $effect(() => {
        void groups;
        void tick().then(() => {
            slideRows();
            padEnd();
            placeSel(true);
            spy();
        });
    });

    export function allExpanded(): boolean {
        return groups.length > 0 && groups.every((g, i) => !isFolded(g.key, i)) && (layout?.sections ?? []).every((s) => !isFolded(s.head.key, -1)) && (archivedGroups.length === 0 || !isFolded('archived', groups.length));
    }

    export function toggleAll(): void {
        const fold = allExpanded();
        setFolds([...(layout?.sections ?? []).map((s) => [s.head.key, fold] as const), ...groups.map((g) => [g.key, fold] as const), ...(archivedGroups.length ? [['archived', fold] as const] : [])]);
        void tick().then(() => placeSel(true));
    }

    export function select(id: string): void {
        if (rows.some((r) => r.s.session_uuid === id)) void choose(id, { focus: false });
    }

    export function openFirst(): void {
        const id = rowEls()[0]?.dataset.id;
        if (id) void choose(id, { open: true });
    }

    onMount(() => {
        if (typeof ResizeObserver === 'undefined' || !listEl) return;
        const ro = new ResizeObserver(() => {
            padEnd();
            placeSel(true);
        });
        ro.observe(listEl);
        return () => ro.disconnect();
    });
</script>

{#snippet project(g: LensGroup, inCompany: boolean)}
    {@const i = groups.indexOf(g)}
    <GroupSection group={g} {inCompany} folded={isFolded(g.key, i)} inactive={bands.inactive.has(g.key)} automatedOnly={typeof g.project?.id === 'number' && data.automatedProjectIds.has(g.project.id)} {onProjectAction} busy={projectBusy} {t} onFold={(key) => toggleFold(key, i)}>
        {@const closed = closedBy.get(historyKeyOf(g)) ?? []}
        {#if g.rows.length === 0 && closed.length === 0}<State class="sp-list-empty" title={t('sessions.page.group.inactive_empty')} />{/if}
        {#each g.rows as r (r.s.session_uuid)}
            <SessionLine
                row={r}
                live={data.live(r.s)}
                latest={data.latest[r.s.session_uuid]}
                measure={lensMeasure(r, lens, ctx)}
                asleepUnread={data.asleepUnread(r.s.session_uuid)}
                selected={r.s.session_uuid === selected}
                {lens}
                now={ctx.now}
                thisComputer={ctx.thisComputer}
                {t}
                {onSelect}
                {onAct}
            />
        {/each}
        {#if closed.length}
            {@render closedList(closed)}
        {/if}
    </GroupSection>
{/snippet}

{#snippet closedList(list: readonly PageRow[])}
    <ClosedRows rows={list} {selected} {busyIds} searching={searching} {t} {age} previousOf={(id) => data.conversations[id] ?? 0} thisComputer={ctx.thisComputer} onSelect={selectClosed} {onAct} />
{/snippet}

<div class="sp-ix" bind:this={rootEl}>
    <LensRail {lens} {counts} groups={groups} inactive={bands.inactive} {current} {listingDown} {t} onLens={setLens} onSection={(key) => void goSection(key)} />
    <div class="sp-listcol">
        {#if bar}
            {@render bar()}
            <div class="sp-sepbar" aria-hidden="true"></div>
        {/if}
        <List
            class="sp-list"
            density="roomy"
            role="listbox"
            tabindex={0}
            label={t('sessions.page.list.label')}
            aria-activedescendant={selected ? `sp-rw-${selected}` : undefined}
            data-lens={lens}
            bind:element={listEl}
            onscroll={onScroll}
        >
            <div class="sp-selbox" bind:this={selbox} hidden aria-hidden="true"></div>
            {#if groups.length || layout?.sections.length || closedOnly.length}
                <ListHead {sort} {lens} {t} {onSort} {onReverse} />
                {#each layout ? layout.sections : [] as sec (sec.head.key)}
                    <GroupSection group={sec.head} company={sec.company} {onCompanyAction} folded={isFolded(sec.head.key, -1)} busy={projectBusy} {t} onFold={(key) => toggleFold(key, -1)} />
                    {#if !isFolded(sec.head.key, -1)}
                        {#each sec.groups as g (g.key)}
                            {@render project(g, true)}
                        {/each}
                    {/if}
                {/each}
                {#each layout ? layout.loose : groups as g (g.key)}
                    {@render project(g, false)}
                {/each}
                {#each closedOnly as g (g.key)}
                    <GroupSection group={g} folded={isFolded(g.key, -1)} {t} onFold={(key) => toggleFold(key, -1)}>
                        {@render closedList(closedBy.get(g.key.slice('closed:'.length)) ?? [])}
                    </GroupSection>
                {/each}
                {#if archivedGroups.length}
                    <GroupSection group={archivedHead} folded={isFolded('archived', groups.length)} inactive {t} onFold={(key) => toggleFold(key, groups.length)}>
                        {#each archivedGroups as g (g.key)}
                            <GroupSection group={g} folded inactive leaf {onProjectAction} busy={projectBusy} {t} onFold={() => {}} />
                        {/each}
                    </GroupSection>
                {/if}
            {:else}
                <State class="sp-list-empty" title={t(rows.length === 0 ? 'sessions.page.empty.match' : 'sessions.page.empty.lens')} />
            {/if}
        </List>
    </div>
</div>
