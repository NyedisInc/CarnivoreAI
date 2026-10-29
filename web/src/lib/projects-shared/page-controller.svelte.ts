import type { Company } from '../companies';
import { resourcePush } from '../resource-push/boot';
import type { Translate } from '../sessions/types';
import type { HistoryApi, HistoryGroup, HistoryPage, HistorySession } from './history-api';
import { pickImageFile } from './image-picker';
import { openMigrate } from '../pack-migrate/migrate-store.svelte';
import { runPackFlow } from './pack-flow';
import { isPackBusy } from './pack-model';
import { MAX_PAGES, overviewQuery, projectQuery } from './history-query';
import { SET_COLOR, SET_COMPANY, companyKeyOf, findSession, type PrimaryId } from './ledger-model';
import {
    ORPHANED,
    PROJECTS_HOME,
    routeHash,
    routeOfHash,
    sameRoute,
    type PageRoute,
} from './route';

export interface ControllerDeps {
    readonly api: HistoryApi;
    readonly t: Translate;
    readonly embedded: boolean;
    readonly close: () => void;
    /*  hidden  */
    readonly pickImage?: () => Promise<File | null>;
    readonly onChanged?: () => void;
}

export interface ListUi {
    query: string;
    psort: string;
    pdir: string;
    hiddenProjects: boolean;
    archivedProjects: boolean;
    hiddenSessions: boolean;
    pstate: string;
}

const isDuplicate = (error: unknown): boolean => (error as { status?: number } | null)?.status === 409;

const PACK_POLL_MS = 5000;

const reason = (error: unknown): string => (error instanceof Error && error.message ? error.message : String(error));

export class ProjectsController {
    route = $state<PageRoute>(PROJECTS_HOME);
    status = $state<'loading' | 'ready' | 'error'>('loading');
    errorText = $state('');
    notice = $state('');
    overview = $state<HistoryGroup[]>([]);
    /* did not answer */
    peerGroups = $state<HistoryGroup[]>([]);
    peerUnavailable = $state<string[]>([]);
    companies = $state<Company[]>([]);
    companiesReady = $state(false);
    companiesFailed = $state(false);
    project = $state<HistoryGroup | null>(null);
    ui = $state<ListUi>({ query: '', psort: 'name', pdir: 'asc', hiddenProjects: false, archivedProjects: false, hiddenSessions: false, pstate: 'all' });
    busy = $state<ReadonlySet<string>>(new Set());
    projectBusy = $state(false);

    readonly #deps: ControllerDeps;
    #ticket = 0;
    #peers: { groups: HistoryGroup[]; unavailable: string[] } = { groups: [], unavailable: [] };
    #drawerPushed = false;

    constructor(deps: ControllerDeps) {
        this.#deps = deps;
    }

    get session(): HistorySession | null {
        const uuid = this.route.session;
        if (!uuid) return null;
        const groups = this.project ? [this.project] : [];
        return findSession(groups, uuid)?.session ?? null;
    }

    go(next: PageRoute): void {
        if (this.#deps.embedded || typeof window === 'undefined') {
            this.applyRoute(next);
            return;
        }
        const hash = routeHash(next);
        if (window.location.hash === hash) this.applyRoute(next);
        else window.location.hash = hash;
    }

    applyRoute(next: PageRoute): void {
        const moved = !sameRoute(this.route, next);
        this.route = next;
        if (moved) this.notice = '';
        void this.load();
    }

    routeFromLocation(): PageRoute {
        return (typeof window === 'undefined' ? null : routeOfHash(window.location.hash)) ?? PROJECTS_HOME;
    }

    async load(): Promise<void> {
        if (this.route.view === 'projects' && this.route.company === ORPHANED && this.route.project === null) {
            this.#replaceRoute(PROJECTS_HOME);
            return;
        }
        const mine = ++this.#ticket;
        const { view, company, project, session } = this.route;
        let redirect: PageRoute | null = null;
        if (this.status !== 'ready') this.status = 'loading';
        if (view === 'projects') void this.#loadCompanies(mine);
        try {
            if (project === null) {
                const groups = await this.#listAll(overviewQuery);
                if (mine !== this.#ticket) return;
                this.overview = groups;
                this.peerGroups = this.#peers.groups;
                this.peerUnavailable = this.#peers.unavailable;
            } else {
                const page = await this.#deps.api.list(projectQuery(project));
                if (mine !== this.#ticket) return;
                this.#checkDatastore(page);
                this.project = page.groups.find((g) => g.key === project) ?? null;
                const real = this.project ? companyKeyOf(this.project) : company === null ? ORPHANED : company;
                if (real !== company) redirect = { view, company: real, project, session };
            }
            this.errorText = '';
            this.status = 'ready';
        } catch (error) {
            if (mine !== this.#ticket) return;
            this.errorText = reason(error);
            this.status = 'error';
            return;
        }
        if (redirect) {
            this.#replaceRoute(redirect);
            return;
        }
    }

    #replaceRoute(next: PageRoute): void {
        if (!this.#deps.embedded && typeof window !== 'undefined') {
            window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${routeHash(next)}`);
        }
        this.applyRoute(next);
    }

    async #loadCompanies(mine: number): Promise<void> {
        const read = this.#deps.api.listCompanies;
        let list: Company[] = [];
        let failed = false;
        if (read) {
            try {
                list = await read();
            } catch (error) {
                failed = true;
                console.error('CloudeOpscenter: projects page could not read the companies', error);
            }
        }
        if (mine !== this.#ticket) return;
        this.setCompanies(list);
        this.companiesFailed = failed;
    }

    setCompanies(list: readonly Company[]): void {
        this.companies = [...list].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id - b.id);
        this.companiesReady = true;
        this.companiesFailed = false;
    }

    async #listAll(query: (offset: number) => string): Promise<HistoryGroup[]> {
        const groups: HistoryGroup[] = [];
        let offset = 0;
        for (let pages = 0; pages < MAX_PAGES; pages += 1) {
            const page = await this.#deps.api.list(query(offset));
            this.#checkDatastore(page);
            if (offset === 0) {
                this.#peers = { groups: [...(page.peer_groups ?? [])], unavailable: (page.peer_unavailable ?? []).map((m) => m.host_label) };
            }
            groups.push(...page.groups);
            if (page.next_offset === null || page.next_offset <= offset) break;
            offset = page.next_offset;
        }
        return groups;
    }

    #checkDatastore(page: HistoryPage): void {
        if (page.state !== 'ok') throw new Error(this.#deps.t('projects.page.no_datastore'));
    }

    async #withBusy(key: string, run: () => Promise<unknown>): Promise<void> {
        this.busy = new Set([...this.busy, key]);
        this.notice = '';
        try {
            const result = (await run()) as { status?: string; detail?: string } | null;
            if (result && result.status === 'refused' && result.detail) this.notice = result.detail;
            await this.load();
        } catch (error) {
            this.notice = reason(error);
        } finally {
            const next = new Set(this.busy);
            next.delete(key);
            this.busy = next;
            this.#deps.onChanged?.();
        }
    }

    async #askName(titleKey: string, current: string, confirmKey = 'projects.page.rename.confirm'): Promise<string | null> {
        const { t, api } = this.#deps;
        const typed = await api.prompt({
            title: t(titleKey),
            label: t('projects.page.rename.label'),
            defaultValue: current,
            confirmLabel: t(confirmKey),
            cancelLabel: t('projects.page.rename.cancel'),
        });
        const name = (typed ?? '').trim();
        return name && name !== current ? name : null;
    }

    act(id: string, session: HistorySession): void {
        const { api, close } = this.#deps;
        const key = session.session_uuid;
        switch (id) {
            case 'open':
                if (api.open(session)) close();
                return;
            case 'wake':
                void this.#withBusy(key, () => api.wake(session));
                return;
            case 'sleep':
                void this.#withBusy(key, () => api.sleep(key));
                return;
            case 'resume':
            case 'restart':
                void this.#withBusy(key, () => api.resume(session));
                return;
            case 'remove':
                void this.#withBusy(key, () => api.removeFromLists(key));
                return;
            case 'put-back':
                void this.#withBusy(key, () => api.restoreToLists(key));
                return;
            case 'rename':
                void (async () => {
                    const name = await this.#askName('projects.page.rename.session_title', session.label ?? session.title);
                    const target = session.live_session_id ?? session.tmux_name;
                    if (name && target) await this.#withBusy(key, () => api.renameSession(target, name));
                })();
                return;
            default:
                console.error('CloudeOpscenter: projects page has no handler for action', id);
        }
    }

    primary(id: PrimaryId, session: HistorySession): void {
        if (id === 'none') return;
        this.act(id, session);
    }

    openSession(session: HistorySession): void {
        const { view, company, project } = this.route;
        const next = { view, company, project, session: session.session_uuid };
        this.#drawerPushed = !this.#deps.embedded && typeof window !== 'undefined' && window.location.hash !== routeHash(next);
        this.go(next);
    }

    closeSession(): void {
        const { view, company, project } = this.route;
        if (this.#drawerPushed && typeof window !== 'undefined') {
            this.#drawerPushed = false;
            window.history.back();
            return;
        }
        this.go({ view, company, project, session: null });
    }

    create(kind: 'session' | 'project'): void {
        const { api, t } = this.#deps;
        const started = kind === 'session' ? api.createSession?.() : api.createProject?.();
        if (!started) this.notice = t('projects.page.notice.create_unavailable');
    }

    projectAction(id: string, target?: HistoryGroup): void {
        const group = target ?? this.project;
        const project = group?.project;
        if (!group || !project) return;
        const { api, t } = this.#deps;
        const run = async (call: () => Promise<unknown>): Promise<void> => {
            this.projectBusy = true;
            this.notice = '';
            try {
                await call();
                await this.load();
            } catch (error) {
                this.notice = this.#words(error);
            } finally {
                this.projectBusy = false;
            }
        };
        switch (id) {
            case 'new-session':
                api.newSession(project);
                return;
            case 'load-blueprint':
                api.openBlueprints();
                return;
            case 'turn-on-agent': {
                const turnOn = api.turnOnAgent;
                const projectId = project.id;
                if (!turnOn || projectId === null) return;
                void (async () => {
                    this.projectBusy = true;
                    this.notice = '';
                    try {
                        const agent = await turnOn(projectId);
                        this.notice = t('projects.page.notice.agent_on', { name: agent.display_name });
                    } catch (error) {
                        this.notice = reason(error);
                    } finally {
                        this.projectBusy = false;
                    }
                })();
                return;
            }
            case 'copy-path':
                if (!project.root) {
                    this.notice = t('projects.page.notice.no_path');
                    return;
                }
                this.notice = '';
                void api.copyText(project.root).then(
                    () => (this.notice = t('projects.page.notice.copied', { path: project.root ?? '' })),
                    (error: unknown) => (this.notice = t('projects.page.notice.copy_failed', { reason: reason(error) })),
                );
                return;
            case 'migrate-project':
            case 'migrate-back':
                openMigrate({ kind: id === 'migrate-back' ? 'back' : 'project', name: project.name });
                return;
            case 'archive-project':
                void run(() => api.archiveProject(project.name));
                return;
            case 'unarchive-project':
                void run(() => api.unarchiveProject(project.name));
                return;
            case 'pack-folder':
            case 'unpack-folder':
                void this.#packFolder(id === 'pack-folder' ? 'pack' : 'unpack', project.name);
                return;
            case 'delete-project':
                void this.#deleteProject(project.name, group.key);
                return;
            case 'rename-project':
                void (async () => {
                    const name = await this.#askName('projects.page.rename.project_title', project.name);
                    if (name) await run(() => api.renameProject(project.name, name));
                })();
                return;
            case 'new-company-for-project':
                void (async () => {
                    const name = await this.#askName('projects.page.company.create_title', '', 'projects.page.company.create_confirm');
                    const create = api.createCompany;
                    const assign = api.setProjectCompany;
                    if (name && create && assign) await run(async () => assign(project.name, (await create(name)).id));
                })();
                return;
            case 'remove-from-company':
                void run(async () => api.setProjectCompany?.(project.name, null));
                return;
            case 'set-image':
                void this.#setImage((file) => api.setProjectImage?.(project.name, file));
                return;
            case 'remove-image':
                void run(async () => api.removeProjectImage?.(project.name));
                return;
            case 'regenerate-art':
                void run(async () => api.regenerateProjectImage?.(project.name));
                return;
            default:
                if (id.startsWith(SET_COLOR)) {
                    const color = id.slice(SET_COLOR.length);
                    void run(() => api.setProjectColor(project.name, color));
                    return;
                }
                if (id.startsWith(SET_COMPANY)) {
                    const companyId = Number(id.slice(SET_COMPANY.length));
                    void run(async () => api.setProjectCompany?.(project.name, companyId));
                    return;
                }
                console.error('CloudeOpscenter: projects page has no handler for project action', id);
        }
    }

    async createCompany(): Promise<void> {
        const create = this.#deps.api.createCompany;
        if (!create) return;
        const name = await this.#askName('projects.page.company.create_title', '', 'projects.page.company.create_confirm');
        if (name) await this.#companyWrite(() => create(name));
    }

    companyAction(id: string, card: { id: number | null; name: string }): void {
        if (card.id === null) return;
        const company = { id: card.id, name: card.name };
        if (id === 'rename-company') void this.renameCompany(company);
        else if (id === 'set-image') void this.setCompanyImage(company);
        else if (id === 'remove-image') void this.removeCompanyImage(company);
        else if (id === 'regenerate-art') void this.regenerateCompanyImage(company);
        else if (id === 'delete-company') void this.deleteCompany(company);
        else if (id === 'migrate-company') openMigrate({ kind: 'company', name: card.name });
    }

    async renameCompany(company: { id: number; name: string }): Promise<void> {
        const rename = this.#deps.api.renameCompany;
        if (!rename) return;
        const name = await this.#askName('projects.page.company.rename_title', company.name);
        if (name) await this.#companyWrite(() => rename(company.id, name));
    }

    async #packFolder(kind: 'pack' | 'unpack', name: string): Promise<void> {
        this.projectBusy = true;
        this.notice = '';
        try {
            const outcome = await runPackFlow(kind, name, this.#deps.api, this.#deps.t);
            this.notice = outcome.notice;
            await this.load();
            if (outcome.started) this.#followSwarm(name);
        } finally {
            this.projectBusy = false;
        }
    }

    #followSwarm(name: string): void {
        const busy = (): boolean => [...this.overview, ...(this.project ? [this.project] : [])]
            .some((g) => g.project?.name === name && isPackBusy(g.project.storage));
        const stop = resourcePush().pushOrPoll(() => void this.load().then(() => { if (!busy()) stop(); }), PACK_POLL_MS, ['projects']);
    }

    async #deleteProject(name: string, key: string): Promise<void> {
        const { api, t } = this.#deps;
        const remove = api.deleteProject;
        if (!remove || !api.confirm) return;
        const yes = await api.confirm({
            title: t('projects.page.project.delete_title'),
            message: t('projects.page.project.delete_message', { name }),
            detail: t('projects.page.project.delete_detail'),
            confirmLabel: t('projects.page.project.delete_confirm'),
            cancelLabel: t('projects.page.rename.cancel'),
        });
        if (!yes) return;
        this.projectBusy = true;
        this.notice = '';
        try {
            await remove(name);
            if (this.route.project === key) this.go(PROJECTS_HOME);
            await this.load();
        } catch (error) {
            this.notice = this.#words(error);
        } finally {
            this.projectBusy = false;
        }
    }

    async deleteCompany(company: { id: number; name: string }): Promise<void> {
        const { api, t } = this.#deps;
        if (!api.deleteCompany || !api.confirm) return;
        const yes = await api.confirm({
            title: t('projects.page.company.delete_title'),
            message: t('projects.page.company.delete_message', { name: company.name }),
            detail: t('projects.page.company.delete_detail'),
            confirmLabel: t('projects.page.company.delete_confirm'),
            cancelLabel: t('projects.page.rename.cancel'),
        });
        if (!yes) return;
        const remove = api.deleteCompany;
        const inside = this.route.company === String(company.id);
        await this.#companyWrite(() => remove(company.id));
        if (inside) this.go(PROJECTS_HOME);
    }

    async setCompanyImage(company: { id: number }): Promise<void> {
        const upload = this.#deps.api.setCompanyImage;
        if (upload) await this.#setImage((file) => upload(company.id, file));
    }

    async removeCompanyImage(company: { id: number }): Promise<void> {
        const remove = this.#deps.api.removeCompanyImage;
        if (remove) await this.#companyWrite(() => remove(company.id));
    }

    async regenerateCompanyImage(company: { id: number }): Promise<void> {
        const regenerate = this.#deps.api.regenerateCompanyImage;
        if (regenerate) await this.#companyWrite(() => regenerate(company.id));
    }

    async #setImage(upload: (file: Blob) => Promise<unknown> | undefined): Promise<void> {
        const file = await (this.#deps.pickImage ?? pickImageFile)();
        if (file) await this.#companyWrite(async () => upload(file));
    }

    #words(error: unknown): string {
        return isDuplicate(error) ? this.#deps.t('projects.page.company.duplicate') : reason(error);
    }

    async #companyWrite(call: () => Promise<unknown>): Promise<void> {
        this.projectBusy = true;
        this.notice = '';
        try {
            await call();
            await this.load();
        } catch (error) {
            this.notice = this.#words(error);
        } finally {
            this.projectBusy = false;
        }
    }

    stop(): void {
        this.#ticket += 1;
    }
}
