/* and writes nothing */
import type { PublishAccount, PublishableSkill, PublishPreview, SubmissionReport } from '../catalog/publish';
import { nodeHash, type MenuNode, type PublishTab } from '../catalog/menu/route';
import type { Translate } from '../sessions/types';
import { failureLine, failureReason } from './failures';
import type { PageHost } from './host';
import type { ActionName, CheckEntry, Facts, Limits, Rules, Source, SubRow, WizardPage } from './types';

export const SUBMISSIONS_TOPIC = 'catalog_submissions';
export const FOLDER_TOPICS = ['local_skills', 'themes', 'mods'] as const;

export interface OpenedStep { ev: string }

interface RulesReturn { mid: OpenedStep | null; view: 'list' | 'dossier' }

export interface PushLike {
    pushOrPoll(refresh: () => void, intervalMs: number, topics: readonly string[]): () => void;
}

export interface PageStoreDeps {
    host: PageHost;
    navigate: (node: MenuNode) => void;
    t: Translate;
}

function isFolderLocation(location: string): boolean {
    return !location.startsWith('item:');
}

const POLL_MS = 60_000;

export class PageStore {
    signedIn = $state(false);
    account = $state<PublishAccount | null>(null);
    mine = $state<SubRow[] | null>(null);
    folders = $state<PublishableSkill[] | null>(null);
    limits = $state<Limits | null>(null);
    rules = $state<Rules | null>(null);
    facts = $state<Record<string, Facts>>({});
    checks = $state<Record<string, CheckEntry>>({});
    staleDigests = $state<Record<string, string>>({});
    staleAt = $state<Record<string, number>>({});
    reports = $state<Record<string, SubmissionReport>>({});
    railFill = $state<Record<string, boolean>>({});
    failure = $state<Record<Source | ActionName, string | null>>({
        account: null, mine: null, folders: null, limits: null, rules: null, facts: null, report: null,
        check: null, send: null, media: null, appeal: null, withdraw: null, register: null,
    });

    foldersReason = $state('');

    tab = $state<PublishTab>('submissions');
    filters = $state<Record<string, string>>({});
    sel = $state<string | null>(null);
    selSub = $state<string | null>(null);
    mid = $state<OpenedStep | null>(null);
    rulesOpen = $state(false);
    from = $state<RulesReturn | null>(null);
    view = $state<'list' | 'dossier'>('list');
    wiz = $state<WizardPage>(0);
    scrollToTop = $state(false);
    restoreTop = $state(false);
    withdrawAsk = $state<string | null>(null);
    forced = $state<Record<string, string>>({});
    flash = $state<string | null>(null);

    readonly #deps: PageStoreDeps;
    #gating = new Map<string, string>();

    constructor(deps: PageStoreDeps) {
        this.#deps = deps;
    }


    async #load<T>(source: Source, read: () => Promise<T>, put: (value: T) => void): Promise<void> {
        try {
            put(await read());
            this.failure[source] = null;
            if (source === 'folders') this.foldersReason = '';
        } catch (error) {
            this.failure[source] = failureLine(source, error, this.#deps.t);
            if (source === 'folders') this.foldersReason = failureReason(source, error, this.#deps.t);
        }
    }

    async #session(): Promise<void> {
        try {
            this.signedIn = (await this.#deps.host.catalogSession()).signed_in === true;
        } catch {
            this.signedIn = false;
        }
    }

    loadAccount(): Promise<void> {
        return this.#load('account', () => this.#deps.host.account(), (v) => { this.account = v; });
    }

    async loadMine(force = false): Promise<void> {
        await this.#load('mine', () => this.#deps.host.mine(force), (rows) => {
            const left: string[] = [];
            for (const row of rows) {
                const before = this.#gating.get(row.id);
                if (before !== undefined && before !== row.gate_state && (before === 'gating' || before === 'received') && row.gate_state !== 'gating') left.push(row.id);
                this.#gating.set(row.id, row.gate_state);
            }
            this.mine = rows;
            for (const id of left) {
                this.railFill[id] = true;
                void this.loadReport(id);
            }
        });
    }

    loadFolders(): Promise<void> {
        return this.#load('folders', async () => (await this.#deps.host.listSkills()).skills ?? [], (v) => { this.folders = v; });
    }

    loadLimits(): Promise<void> {
        return this.#load('limits', () => this.#deps.host.limits(), (v) => { this.limits = v; });
    }

    loadRules(): Promise<void> {
        return this.#load('rules', () => this.#deps.host.rules(), (v) => { this.rules = v; });
    }

    loadFacts(location: string): Promise<void> {
        return this.#load('facts', () => this.#deps.host.facts(location), (v) => {
            this.facts[location] = v;
            const stored = this.checks[location] ? null : this.storedSendable(location);
            if (stored) this.checks[location] = stored;
        });
    }

    loadReport(id: string): Promise<void> {
        const row = this.mine?.find((r) => r.id === id);
        if (row && (row.gate_state === 'received' || row.gate_state === 'gating')) return Promise.resolve();
        return this.#load('report', () => this.#deps.host.report(id), (v) => { this.reports[id] = v; });
    }

    async open(force = false): Promise<void> {
        await this.#session();
        const hosted = this.signedIn ? [this.loadAccount(), this.loadMine(force), this.loadLimits()] : [];
        await Promise.all([this.loadFolders(), this.loadRules(), ...hosted]);
        if (this.sel && isFolderLocation(this.sel)) await this.loadFacts(this.sel);
        const step = this.mid?.ev.endsWith(':gates') ? this.mid.ev.slice(0, -':gates'.length) : null;
        if (step) await this.loadReport(step);
    }

    refresh(): Promise<void> {
        return this.open(true);
    }

    async onTopic(topic: string): Promise<void> {
        if (topic === SUBMISSIONS_TOPIC) {
            if (!this.signedIn) return;
            await this.loadMine();
            await this.loadLimits();
        } else if ((FOLDER_TOPICS as readonly string[]).includes(topic)) {
            await this.loadFolders();
        }
    }

    connect(push: PushLike): () => void {
        const stops = [
            push.pushOrPoll(() => void this.onTopic(SUBMISSIONS_TOPIC), POLL_MS, [SUBMISSIONS_TOPIC]),
            push.pushOrPoll(() => void this.onTopic('local_skills'), POLL_MS, FOLDER_TOPICS),
        ];
        return () => stops.forEach((stop) => stop());
    }


    async reloadAfterWrite(location: string | null): Promise<void> {
        await Promise.all([this.loadMine(), this.loadLimits(), location && isFolderLocation(location) ? this.loadFacts(location) : Promise.resolve()]);
    }

    async reloadAfterRegister(): Promise<void> {
        await Promise.all([this.loadAccount(), this.loadLimits()]);
    }

    setActionFailure(name: ActionName, error: unknown): void {
        this.failure[name] = error === null ? null : failureLine(name, error, this.#deps.t);
    }

    checkOf(location: string): CheckEntry | null {
        const mine = this.checks[location];
        if (mine) return mine;
        const record = this.facts[location]?.checks[0];
        if (record && this.#refused(location, record)) return null;
        return record ? { version: record.version, ok: record.ok, at: record.at, summary: record.summary, preview: null, findings: record.findings } : null;
    }

    #refused(location: string, record: { digest?: string; at: string }): boolean {
        if (!(location in this.staleDigests)) return false;
        if (record.digest) return this.staleDigests[location] === record.digest;
        return (Date.parse(record.at) || 0) <= (this.staleAt[location] ?? 0);
    }

    storedSendable(location: string): CheckEntry | null {
        const facts = this.facts[location];
        const record = facts?.checks[0];
        if (!record || !record.ok || !record.digest || this.#refused(location, record)) return null;
        const sent = facts.sends[0];
        if (sent && (Date.parse(sent.sent_at) || 0) >= (Date.parse(record.at) || 0)) return null;
        const preview: PublishPreview = {
            location, name: '', version: record.version, file_count: record.files ?? 0, total_bytes: record.bytes ?? 0, files: [], refusals: [],
            lint: { grade: record.grade ?? '' }, cost: {}, compat: {}, digest: record.digest, can_send: true,
        };
        return { version: record.version, ok: true, at: record.at, summary: record.summary, preview };
    }


    #here(): MenuNode {
        if (this.rulesOpen) return { scope: 'publish', page: 'rules' };
        if (this.sel && this.view === 'dossier') return { scope: 'publish', page: 'item', tab: this.tab, location: this.sel, ...(this.mid ? { event: this.mid.ev } : {}) };
        return { scope: 'publish', page: 'tab', tab: this.tab };
    }

    #go(): void {
        this.scrollToTop = true;
        this.#deps.navigate(this.#here());
    }

    applyNode(node: MenuNode): void {
        if (node.scope !== 'publish') return;
        if (nodeHash(node) === nodeHash(this.#here())) return;
        if (node.page === 'rules') {
            if (!this.rulesOpen) this.from = { mid: this.mid, view: this.view };
            this.rulesOpen = true;
            this.view = 'dossier';
            return;
        }
        this.rulesOpen = false;
        this.from = null;
        this.tab = node.tab;
        if (node.page === 'item') {
            if (this.sel !== node.location) this.selSub = null;
            this.sel = node.location;
            this.mid = node.event ? { ev: node.event } : null;
            this.view = 'dossier';
        } else {
            this.sel = null;
            this.selSub = null;
            this.mid = null;
            this.view = 'list';
            this.restoreTop = true;
        }
    }


    setTab(tab: PublishTab): void {
        this.tab = tab;
        this.rulesOpen = false;
        this.from = null;
        this.view = 'list';
        this.#go();
    }

    select(location: string, sub: string | null = null, tab?: PublishTab): void {
        if (tab) this.tab = tab;
        this.withdrawAsk = null;
        this.wiz = 0;
        this.sel = location;
        this.selSub = sub;
        this.mid = null;
        this.rulesOpen = false;
        this.from = null;
        this.view = 'dossier';
        this.flash = location;
        this.#go();
        if (isFolderLocation(location) && !this.facts[location]) void this.loadFacts(location);
    }

    showDefault(location: string, sub: string | null): void {
        if (this.sel || this.rulesOpen) return;
        this.sel = location;
        this.selSub = sub;
        if (isFolderLocation(location) && !this.facts[location]) void this.loadFacts(location);
    }

    askWithdraw(id: string): void {
        this.withdrawAsk = id;
    }

    forceNew(location: string, latestId: string): void {
        this.forced[location] = latestId;
    }

    openEvent(key: string): void {
        if (!this.sel) return;
        this.mid = { ev: key };
        this.rulesOpen = false;
        this.#go();
        if (key.endsWith(':gates')) {
            const id = key.slice(0, -':gates'.length);
            if (!this.reports[id]) void this.loadReport(id);
        }
    }

    closeEvent(): void {
        this.mid = null;
        this.#go();
    }

    openRules(): void {
        if (this.rulesOpen) return;
        this.from = { mid: this.mid, view: this.view };
        this.rulesOpen = true;
        this.view = 'dossier';
        this.#go();
    }

    closeRules(): void {
        if (!this.rulesOpen) return;
        const back = this.from ?? { mid: null, view: 'list' as const };
        this.rulesOpen = false;
        this.mid = back.mid;
        this.view = back.view;
        this.from = null;
        this.#go();
    }

    goList(): void {
        this.rulesOpen = false;
        this.from = null;
        this.view = 'list';
        this.#go();
    }

    setFilter(tab: PublishTab, text: string): void {
        this.filters[tab] = text;
    }

    setWizard(page: WizardPage): void {
        this.wiz = page;
    }
}

export function createPageStore(deps: PageStoreDeps): PageStore {
    return new PageStore(deps);
}
