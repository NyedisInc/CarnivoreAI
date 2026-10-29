<!-- the overlay host -->
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import { onMount, tick } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import Page from '../../opscenter/ui/Page.svelte';
    import Field from '../base/Field.svelte';
    import State from '../base/State.svelte';
    import Toolbar from '../base/Toolbar.svelte';
    import { viewport } from '../../opscenter/engine/viewport.svelte';
    import '../projects-shared/projects-shared.css';
    import { ProjectsController } from '../projects-shared/page-controller.svelte';
    import { historyApi, type HistoryApi } from '../projects-shared/history-api';
    import type { Translate } from '../sessions/types';
    import FilterBar from './FilterBar.svelte';
    import FleetSummary from './FleetSummary.svelte';
    import ListView from './ListView.svelte';
    import PivotView from './PivotView.svelte';
    import SessionPanel from './SessionPanel.svelte';
    import TimelineView from './TimelineView.svelte';
    import TitleStrip from './TitleStrip.svelte';
    import TitleActions from './TitleActions.svelte';
    import ViewSwitch from './ViewSwitch.svelte';
    import MigrateWizard from '../pack-migrate/MigrateWizard.svelte';
    import ProjectToolWindow from './ProjectToolWindow.svelte';
    import { toolOf, type ProjectTool } from './project-tools';
    import { NO_FILTERS, distinct, fleetCounts, matchesFind, passes, type Filters, type PageRow } from './filters';
    import type { LensGroup } from './lenses';
    import type { PanelAction } from './row-action';
    import { closedShown } from './closed-model';
    import './sessions-page.css';
    import { SessionsData, defaultReaders, type SessionsReaders } from './sessions-data.svelte';
    import { SESSIONS_TOP, projectOfHash, sessionsHash, sessionsRouteOfHash, type SessionsRoute } from './sessions-route';
    import { readView, writeView, type SessionsView } from './views';
    import { readProjectSort, readShowHidden, writeProjectSort, writeShowHidden, type ProjectSortKey } from './toolbar-prefs';

    interface Props {
        api?: HistoryApi;
        readers?: SessionsReaders;
        t?: Translate;
        embedded?: boolean;
        now?: () => number;
    }
    const { api = historyApi, readers = defaultReaders, t = reactiveT, embedded = false, now = () => Date.now() }: Props = $props();

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let titleEl = $state<HTMLHeadingElement | undefined>();
    let notice = $state('');
    let view = $state<SessionsView>(readView());
    let route = $state<SessionsRoute>(SESSIONS_TOP);
    let pendingProject = $state<string | null>(null);
    let filters = $state<Filters>({ ...NO_FILTERS });
    let selected = $state<string | null>(null);
    let list = $state<ReturnType<typeof ListView> | undefined>();
    let timeline = $state<ReturnType<typeof TimelineView> | undefined>();
    let showHidden = $state(readShowHidden());
    let projectSort = $state<ProjectSortKey>(readProjectSort());
    let pageRoot = $state<HTMLDivElement | undefined>();
    let projectTool = $state<{ tool: ProjectTool; project: { id: number; name: string } } | null>(null);

    // svelte-ignore state_referenced_locally
    const data = new SessionsData(api, readers, t('sessions.page.filter.no_project'), t('sessions.page.notice.no_datastore'));
    // svelte-ignore state_referenced_locally
    data.showHidden = showHidden;

    // svelte-ignore state_referenced_locally
    const projectCtl = new ProjectsController({ api, t, embedded: true, close: () => close(), onChanged: () => void data.refresh() });
    function projectAction(id: string, group: LensGroup): void {
        if (!group.project) return;
        const tool = toolOf(id);
        if (tool) {
            if (group.project.id != null) projectTool = { tool, project: { id: group.project.id, name: group.project.name } };
            return;
        }
        projectCtl.projectAction(id, { key: group.key, project: group.project, session_total: group.count, counts: {}, last_activity_at: null, sessions: [] });
    }
    const shownNotice = $derived(notice || projectCtl.notice);
    const withEmpties = $derived(filters.on.includes('working') && filters.on.includes('sleep') && !filters.company && !filters.project && !filters.computer && !filters.provider);

    const labels = $derived({ noCompany: t('sessions.page.filter.no_company'), thisComputer: t('sessions.page.filter.this_computer') });
    const rows = $derived(data.rows);
    const shown = $derived(rows.filter((r) => passes(r, filters, data, labels)));
    const closedShownRows = $derived(data.closedRows.filter((r) => closedShown(r, filters, labels, showHidden)));
    const timelineRows = $derived(rows.filter((r) => matchesFind(r, filters.q)));
    const counts = $derived(fleetCounts(rows, data, now()));
    const companies = $derived(distinct(rows.map((r) => r.company ?? labels.noCompany)));
    const projects = $derived(distinct(rows.map((r) => r.project)));
    const computers = $derived(distinct([...rows, ...data.closedRows].map((r) => r.computer ?? labels.thisComputer)));
    const providers = $derived(distinct(rows.map((r) => r.provider)));
    const historyFailed = $derived(data.status === 'error');
    const panelRow = $derived(route.session ? (rows.find((r) => r.s.session_uuid === route.session) ?? data.closedRows.find((r) => r.s.session_uuid === route.session) ?? null) : null);
    const narrow = $derived(viewport.narrow && !embedded);

    const folds = $derived(view === 'list' ? list : view === 'timeline' ? timeline : undefined);

    function toggleHidden(): void {
        showHidden = !showHidden;
        writeShowHidden(showHidden);
        data.setShowHidden(showHidden);
    }

    function setProjectSort(next: ProjectSortKey): void {
        projectSort = next;
        writeProjectSort(next);
    }

    function setView(next: SessionsView): void {
        view = next;
        writeView(next);
    }

    function act(kind: PanelAction, r: PageRow): void {
        notice = '';
        if (kind === 'resume' || kind === 'restart' || kind === 'put-back' || kind === 'remove') {
            if (r.computer === null) projectCtl.act(kind, r.s);
        } else if (kind === 'open') {
            if (api.open(r.s)) close();
            else notice = t('sessions.page.notice.open_failed');
        } else if (kind === 'wake') {
            void api.wake(r.s).then(
                (result) => {
                    if (result?.status === 'refused' && result.detail) notice = result.detail;
                },
                (error: unknown) => {
                    notice = error instanceof Error ? error.message : String(error);
                },
            );
        } else if (!(r.projectRef ? api.newSession(r.projectRef) : api.createSession?.())) {
            notice = t('projects.page.notice.create_unavailable');
        }
    }

    function preview(sessionUuid: string | null): void {
        route = sessionUuid ? { session: sessionUuid } : SESSIONS_TOP;
        if (open && typeof window !== 'undefined' && sessionsHash(route) !== window.location.hash) {
            window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${sessionsHash(route)}`);
        }
    }

    function closePanel(): void {
        preview(null);
        pageRoot?.querySelector<HTMLElement>('.sp-list')?.focus({ preventScroll: true });
    }

    function findKey(e: KeyboardEvent): void {
        if (e.key === 'ArrowDown' || e.key === 'Enter') {
            if (view === 'list') {
                e.preventDefault();
                list?.openFirst();
            }
        } else if (e.key === 'Escape') {
            filters.q = '';
            (e.currentTarget as HTMLInputElement).blur();
        }
    }

    function pageKey(e: KeyboardEvent): void {
        const target = e.target as HTMLElement | null;
        if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey || !target || /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName) || target.isContentEditable) return;
        e.preventDefault();
        pageRoot?.querySelector<HTMLInputElement>('input[type="search"]')?.focus();
    }

    export function show(): void {
        if (!open) {
            opener = captureOpener();
            open = true;
        }
        route = (typeof window === 'undefined' ? null : sessionsRouteOfHash(window.location.hash)) ?? SESSIONS_TOP;
        pendingProject = typeof window === 'undefined' ? null : projectOfHash(window.location.hash);
        void tick().then(() => (route.session ? undefined : titleEl?.focus()));
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        if (typeof window !== 'undefined' && sessionsRouteOfHash(window.location.hash)) {
            window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
        }
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    $effect(() => data.setShowArchived(filters.on.includes('archived')));
    $effect(() => {
        if (!open) return;
        data.start();
        return () => data.stop();
    });

    $effect(() => {
        const id = route.session;
        if (id && list && view === 'list' && data.status === 'ready' && selected !== id) list.select(id);
    });

    $effect(() => {
        if (!pendingProject || data.status !== 'ready') return;
        const all = [...rows.map((r) => r.projectRef), ...data.emptyProjects, ...data.archivedProjects];
        const hit = all.find((p) => p !== null && String(p.id) === pendingProject);
        pendingProject = null;
        if (hit) filters = { ...filters, project: hit.name };
    });

    // the overlay host
    onMount(() => {
        if (embedded && typeof window !== 'undefined') {
            route = sessionsRouteOfHash(window.location.hash) ?? SESSIONS_TOP;
            pendingProject = projectOfHash(window.location.hash);
        }
    });
</script>

{#snippet findField()}
    <Field variant="search" block type="search" bind:value={filters.q} placeholder={t('sessions.page.find.placeholder')} label={t('sessions.page.find.label')}
        clearLabel={t('sessions.page.find.clear')} autocomplete="off" spellcheck="false" onkeydown={findKey} />
{/snippet}

{#snippet pageSub()}
    <TitleStrip title={t('sessions.page.title')} onNewProject={() => projectCtl.create('project')} onNewCompany={() => void projectCtl.createCompany()} onNewSession={() => projectCtl.create('session')} {showHidden} onToggleHidden={toggleHidden} showFold={!!folds} allOpen={folds?.allExpanded() ?? false} onToggleAll={() => folds?.toggleAll()} find={findField} {counts} listingDown={data.listingDown} {historyFailed} {t} />
{/snippet}

{#snippet phoneBar()}
    <div class="sp-phonebar">
        <div class="sp-tbl">
            <span class="pl-title" aria-hidden="true">{t('sessions.page.title')}</span>
            <TitleActions onNewProject={() => projectCtl.create('project')} onNewCompany={() => void projectCtl.createCompany()} onNewSession={() => projectCtl.create('session')} {showHidden} onToggleHidden={toggleHidden} showFold={!!folds} allOpen={folds?.allExpanded() ?? false} onToggleAll={() => folds?.toggleAll()} {t} />
        </div>
        <div class="sp-find">{@render findField()}</div>
        <FleetSummary {counts} listingDown={data.listingDown} {historyFailed} {t} />
    </div>
{/snippet}

{#snippet pageNotes()}
    {#if shownNotice}<p class="oc-notice" role="status" data-notice>{shownNotice}</p>{/if}
    {#if data.listingDown}<p class="oc-notice" role="status" data-strip="listing">{t('sessions.page.notice.listing_down')}</p>{/if}
    {#if historyFailed}<p class="oc-notice" role="status" data-strip="history">{data.errorText || t('sessions.page.notice.history_failed')}</p>{/if}
{/snippet}

{#snippet filterBar()}
    <FilterBar {view} onView={setView} bind:filters {companies} {projects} {computers} {providers} {projectSort} onProjectSort={setProjectSort} shown={shown.length} total={rows.length} {t} />
{/snippet}

{#if open}
    <Page
        class="sp-page"
        {embedded}
        title={t('sessions.page.title')}
        bind:titleEl
        bind:root={pageRoot}
        onkeydown={pageKey}
        onClose={embedded ? undefined : close}
        sub={narrow ? undefined : pageSub}
        bar={narrow ? phoneBar : undefined}
        notes={shownNotice || data.listingDown || historyFailed ? pageNotes : undefined}
        data-view={view}
        data-session={route.session ?? undefined}
    >
        <div class="oc-page__body sp-body">
            <MigrateWizard />
            {#if projectTool}<ProjectToolWindow tool={projectTool.tool} project={projectTool.project} {t} onClose={() => (projectTool = null)} />{/if}
            {#if view !== 'list'}
                <Toolbar band class="sp-bar sp-bar--solo" label={t('sessions.page.view.label')}>
                    {#snippet end()}
                        <ViewSwitch {view} onView={setView} {t} />
                        <span class="sp-count" aria-live="polite">{t('sessions.page.count', { shown: rows.length, total: rows.length })}</span>
                    {/snippet}
                </Toolbar>
                <div class="sp-sepbar" aria-hidden="true"></div>
            {/if}
            <div class="sp-hosts" data-panel={route.session ? '' : undefined}>
                <div class="sp-host" data-host="list" role="region" aria-label={t('sessions.page.host.list')} hidden={view !== 'list'}>
                    {#if data.status === 'loading'}<State class="sp-empty" kind="loading" title={t('sessions.page.loading')} />
                    {:else if data.status === 'ready' && rows.length === 0 && data.emptyProjects.length === 0 && data.archivedProjects.length === 0}<State class="sp-empty" title={t('sessions.page.empty')} />
                    {:else if data.status === 'ready'}
                        <ListView bind:this={list} rows={shown} closedRows={closedShownRows} busyIds={projectCtl.busy} {data} {t} {now} searching={filters.q.trim() !== ''} emptyProjects={data.emptyProjects} find={filters.q} {withEmpties} showArchived={filters.on.includes('archived')} {projectSort} onProjectAction={projectAction} onCompanyAction={(id, company) => projectCtl.companyAction(id, company)} projectBusy={projectCtl.projectBusy} active={view === 'list'} bar={filterBar} bind:selected previewing={route.session !== null} onPreview={preview} onAct={act} />
                    {/if}
                </div>
                <div class="sp-host" data-host="pivot" role="region" aria-label={t('sessions.page.host.pivot')} hidden={view !== 'pivot'}>
                    {#if view === 'pivot' && data.status === 'ready' && rows.length > 0}
                        <PivotView {rows} find={filters.q} {data} {t} {now} selected={route.session} panelOpen={route.session !== null} {historyFailed} onPreview={preview} onAct={act} />
                    {:else if view === 'pivot' && data.status === 'loading'}<State class="sp-empty" kind="loading" title={t('sessions.page.loading')} />
                    {:else if view === 'pivot' && data.status === 'ready'}<State class="sp-empty" title={t('sessions.page.empty')} />
                    {/if}
                </div>
                <div class="sp-host" data-host="timeline" role="region" aria-label={t('sessions.page.host.timeline')} hidden={view !== 'timeline'}>
                    {#if view === 'timeline' && data.status === 'ready' && rows.length > 0}
                        <TimelineView bind:this={timeline} rows={timelineRows} {data} {t} {now} selected={route.session} onPreview={(id) => preview(id)} />
                    {:else if view === 'timeline' && data.status === 'loading'}<State class="sp-empty" kind="loading" title={t('sessions.page.loading')} />
                    {:else if view === 'timeline' && data.status === 'ready'}<State class="sp-empty" title={t('sessions.page.empty')} />
                    {/if}
                </div>
                {#if route.session}
                    <SessionPanel row={panelRow} ready={data.status === 'ready'} busyIds={projectCtl.busy} {data} {t} {now} onClose={closePanel} onAct={act} />
                {/if}
            </div>
        </div>
    </Page>
{/if}
