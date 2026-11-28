import { auth, authFetchStream } from '../../opscenter/api/auth.svelte';
import { pluginsStore, type PluginInspectorSnapshot } from '../plugins/store.svelte';
import { activeThemeId, themeChoices, type ThemeChoice } from '../../plugins/sdk/themes';
import {
    createWorkspace as apiCreateWorkspace,
    deleteWorkspace as apiDeleteWorkspace,
    getReadiness as apiGetReadiness,
    getWorkspace as apiGetWorkspace,
    installWorkspace as apiInstallWorkspace,
    launchAgent as apiLaunchAgent,
    listWorkspaces as apiListWorkspaces,
    previewRender as apiPreviewRender,
    publishWorkspace as apiPublishWorkspace,
    runReadiness as apiRunReadiness,
    startDev as apiStartDev,
    stopDev as apiStopDev,
    testSandbox as apiTestSandbox,
    extractStudioError,
    type StudioFetcher,
} from './api';
import { defaultPreviewThemes } from './theme-bridge';
import type {
    CreateWorkspaceRequest,
    InstallWorkspaceRequest,
    InstallWorkspaceResult,
    LaunchAgentRequest,
    PreviewRenderResponse,
    PublishWorkspaceRequest,
    PublishWorkspaceResult,
    ReadinessReport,
    SandboxTestReport,
    StudioActionError,
    StudioBusyAction,
    StudioWorkspace,
    TestSandboxRequest,
    WorkspaceDetailResponse,
} from './types';

export type { StudioBusyAction };

export interface DevStreamRecord {
    id: string;
    type: string;
    payload: unknown;
    at: string;
}

const DEV_STREAM_REFRESH_EVENTS = new Set([
    'reloaded',
    'permission_widened',
    'reload_error',
    'ui_error',
    'lease_acquired',
    'lease_released',
    'message',
]);

const DEV_STREAM_EVENTS = new Set([
    'reloaded',
    'reload_error',
    'permission_widened',
    'ui_error',
    'stderr',
    'lease_acquired',
    'lease_released',
    'message',
    'error',
]);

export type StudioStreamOpener = (path: string, init: RequestInit) => Promise<Response>;

export class StudioStore {
    workspaces = $state<StudioWorkspace[]>([]);
    activeId = $state<string | null>(null);
    detail = $state<WorkspaceDetailResponse | null>(null);
    loading = $state(false);
    busyAction = $state<StudioBusyAction>(null);
    error = $state<StudioActionError | null>(null);

    selectedThemes = $state<string[]>(defaultPreviewThemes());
    surfaceId = $state<string | null>(null);
    viewportWidth = $state<number>(480);
    viewportHeight = $state<number>(320);
    previewByTheme = $state<Record<string, PreviewRenderResponse>>({});

    readiness = $state<ReadinessReport | null>(null);
    sandboxResult = $state<SandboxTestReport | null>(null);
    installResult = $state<InstallWorkspaceResult | null>(null);
    publishPreview = $state<PublishWorkspaceResult | null>(null);
    publishResult = $state<PublishWorkspaceResult | null>(null);
    devEvents = $state<DevStreamRecord[]>([]);

    private fetcher: StudioFetcher | undefined = undefined;
    private streamOpener: StudioStreamOpener | undefined = undefined;
    private devAbort: AbortController | null = null;
    private devStreamPluginId: string | null = null;
    private devStreamSeq = 0;
    private releaseInspector: (() => void) | null = null;
    private inspectorPluginId = $state<string | null>(null);
    private lifecycleGen = 0;
    private listGen = 0;
    private detailGen = 0;
    private previewGen = 0;

    get pluginInspector(): PluginInspectorSnapshot | null {
        return this.inspectorPluginId ? (pluginsStore.inspectors[this.inspectorPluginId] ?? null) : null;
    }

    setFetcherForTest(fetcher: StudioFetcher | undefined): void {
        this.fetcher = fetcher;
    }

    setStreamOpenerForTest(opener: StudioStreamOpener | undefined): void {
        this.streamOpener = opener;
    }

    themeOptions(): ThemeChoice[] {
        return themeChoices();
    }

    ensureSelectedThemes(): string[] {
        const choices = this.themeOptions();
        const available = new Set(choices.map((c) => c.id));
        const valid = this.selectedThemes.filter((id) => available.size === 0 || available.has(id));
        if (valid.length >= 2 || (available.size <= 1 && valid.length >= 1)) {
            return valid;
        }
        const defaults = defaultPreviewThemes(choices, activeThemeId());
        for (const id of defaults) {
            if (!valid.includes(id)) valid.push(id);
        }
        this.selectedThemes = valid;
        return valid;
    }

    toggleTheme(themeId: string): void {
        const next = this.selectedThemes.includes(themeId)
            ? this.selectedThemes.filter((id) => id !== themeId)
            : [...this.selectedThemes, themeId];
        if (next.length === 0) return;
        this.selectedThemes = next;
        if (this.activeId) {
            void this.refreshPreviews(this.activeId);
        }
    }

    setViewport(width: number, height: number): void {
        this.viewportWidth = width;
        this.viewportHeight = height;
        if (this.activeId) {
            void this.refreshPreviews(this.activeId);
        }
    }

    setSurface(surfaceId: string | null): void {
        this.surfaceId = surfaceId;
        if (this.activeId) {
            void this.refreshPreviews(this.activeId);
        }
    }

    clearError(): void {
        this.error = null;
    }

    resetPublishState(): void {
        this.publishPreview = null;
        this.publishResult = null;
    }

    async refreshWorkspaces(preferredId?: string | null): Promise<StudioWorkspace[]> {
        if (!this.fetcher && auth.state === 'signed-out') {
            return this.workspaces;
        }
        const lGen = this.lifecycleGen;
        const listGen = ++this.listGen;
        this.busyAction = 'list';
        this.loading = true;
        try {
            const list = await apiListWorkspaces(this.fetcher);
            if (listGen !== this.listGen) return this.workspaces;
            this.workspaces = list;
            this.error = null;
            this.loading = false;
            if (this.busyAction === 'list') this.busyAction = null;
            if (lGen !== this.lifecycleGen) return list;
            const targetId = preferredId ?? this.activeId ?? list[0]?.studio_id ?? null;
            if (targetId && list.some((w) => w.studio_id === targetId)) {
                await this.selectWorkspace(targetId);
            } else if (list.length === 0 || (this.activeId && !list.some((w) => w.studio_id === this.activeId))) {
                this.clearActiveWorkspace();
            }
            return list;
        } catch (err) {
            if (listGen === this.listGen) {
                this.error = extractStudioError(err);
            }
            return this.workspaces;
        } finally {
            if (listGen === this.listGen) {
                this.loading = false;
                if (this.busyAction === 'list') this.busyAction = null;
            }
        }
    }

    async createAndLaunch(body: CreateWorkspaceRequest): Promise<WorkspaceDetailResponse | null> {
        const gen = this.lifecycleGen;
        this.busyAction = 'create';
        this.error = null;
        this.sandboxResult = null;
        this.installResult = null;
        this.resetPublishState();
        try {
            const created = await apiCreateWorkspace(body, this.fetcher);
            if (gen !== this.lifecycleGen) return null;
            const list = await apiListWorkspaces(this.fetcher);
            if (gen !== this.lifecycleGen) return null;
            this.workspaces = list;
            if (created.dev?.active) {
                await pluginsStore.refresh({ force: true });
                if (gen !== this.lifecycleGen) return null;
            }
            if (this.busyAction === 'create') this.busyAction = null;
            return await this.selectWorkspace(created.workspace.studio_id);
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return null;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'create') this.busyAction = null;
        }
    }

    async selectWorkspace(studioId: string): Promise<WorkspaceDetailResponse | null> {
        const switching = this.activeId !== studioId;
        if (switching) {
            this.lifecycleGen += 1;
            this.listGen += 1;
            this.detailGen += 1;
            this.previewGen += 1;
            this.loading = false;
            this.detail = null;
            this.readiness = null;
            this.surfaceId = null;
            this.sandboxResult = null;
            this.installResult = null;
            this.resetPublishState();
            this.previewByTheme = {};
            this.devEvents = [];
            this.closeDevStream();
            this.releaseInspectorHandle();
        }
        this.activeId = studioId;
        return await this.refreshDetail(studioId);
    }

    async refreshDetail(studioId: string = this.activeId ?? ''): Promise<WorkspaceDetailResponse | null> {
        if (!studioId) return null;
        const lGen = this.lifecycleGen;
        const dGen = ++this.detailGen;
        const stale = (): boolean => lGen !== this.lifecycleGen || dGen !== this.detailGen;
        this.busyAction = 'detail';
        try {
            const detail = await apiGetWorkspace(studioId, this.fetcher);
            if (stale()) return null;
            this.detail = detail;
            this.readiness = detail.workspace.last_readiness ?? null;
            this.syncWorkspaceRow(detail.workspace);
            this.syncDevStream(detail.dev_status.active ? detail.dev_status.plugin_id : null);
            this.syncInspectorLease(detail.workspace.plugin_id, detail.dev_status.active);
            const themes = this.ensureSelectedThemes();
            const firstTheme = themes[0];
            if (firstTheme && !this.previewByTheme[firstTheme]) {
                this.previewByTheme = { ...this.previewByTheme, [firstTheme]: detail.preview };
            }
            this.error = null;
            await this.refreshPreviews(studioId);
            if (stale()) return null;
            return detail;
        } catch (err) {
            if (!stale()) {
                if (this.detail?.workspace.studio_id !== studioId) {
                    this.detail = null;
                }
                this.error = extractStudioError(err);
            }
            return null;
        } finally {
            if (!stale() && this.busyAction === 'detail') this.busyAction = null;
        }
    }

    async removeWorkspace(studioId: string, deleteFiles = true): Promise<boolean> {
        const gen = this.lifecycleGen;
        this.busyAction = 'delete';
        this.error = null;
        try {
            await apiDeleteWorkspace(studioId, deleteFiles, this.fetcher);
            if (gen !== this.lifecycleGen) return false;
            this.workspaces = this.workspaces.filter((w) => w.studio_id !== studioId);
            if (this.busyAction === 'delete') this.busyAction = null;
            if (this.activeId === studioId) {
                const next = this.workspaces[0]?.studio_id ?? null;
                if (next) {
                    await this.selectWorkspace(next);
                } else {
                    this.clearActiveWorkspace();
                }
            }
            return true;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return false;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'delete') this.busyAction = null;
        }
    }

    async relaunchAgent(body: LaunchAgentRequest = {}): Promise<boolean> {
        const studioId = this.activeId;
        if (!studioId) return false;
        const gen = this.lifecycleGen;
        this.busyAction = 'agent';
        this.error = null;
        try {
            await apiLaunchAgent(studioId, body, this.fetcher);
            if (gen !== this.lifecycleGen) return false;
            await this.refreshDetail(studioId);
            return gen === this.lifecycleGen;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return false;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'agent') this.busyAction = null;
        }
    }

    async startDevMode(autoApprove = true): Promise<boolean> {
        const studioId = this.activeId;
        if (!studioId) return false;
        const gen = this.lifecycleGen;
        this.busyAction = 'dev';
        this.error = null;
        try {
            await apiStartDev(studioId, { auto_approve: autoApprove }, this.fetcher);
            if (gen !== this.lifecycleGen) return false;
            await pluginsStore.refresh({ force: true });
            if (gen !== this.lifecycleGen) return false;
            await this.refreshDetail(studioId);
            return gen === this.lifecycleGen;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return false;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'dev') this.busyAction = null;
        }
    }

    async stopDevMode(): Promise<boolean> {
        const studioId = this.activeId;
        if (!studioId) return false;
        const gen = this.lifecycleGen;
        this.busyAction = 'dev';
        this.error = null;
        try {
            await apiStopDev(studioId, this.fetcher);
            if (gen !== this.lifecycleGen) return false;
            this.closeDevStream();
            await pluginsStore.refresh({ force: true });
            if (gen !== this.lifecycleGen) return false;
            await this.refreshDetail(studioId);
            return gen === this.lifecycleGen;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return false;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'dev') this.busyAction = null;
        }
    }

    async refreshPreviews(studioId: string = this.activeId ?? ''): Promise<void> {
        if (!studioId) return;
        const lGen = this.lifecycleGen;
        const pGen = ++this.previewGen;
        const stale = (): boolean =>
            lGen !== this.lifecycleGen || pGen !== this.previewGen || this.activeId !== studioId;
        const themes = this.ensureSelectedThemes();
        const prevBusy = this.busyAction === 'preview' ? null : this.busyAction;
        if (!prevBusy) this.busyAction = 'preview';
        try {
            const entries = await Promise.all(
                themes.map(async (themeId) => {
                    const rendered = await apiPreviewRender(
                        studioId,
                        {
                            theme_id: themeId,
                            width: this.viewportWidth,
                            height: this.viewportHeight,
                            surface_id: this.surfaceId,
                        },
                        this.fetcher,
                    );
                    return [themeId, rendered] as const;
                }),
            );
            if (stale()) return;
            const next: Record<string, PreviewRenderResponse> = {};
            for (const [themeId, rendered] of entries) {
                next[themeId] = rendered;
            }
            this.previewByTheme = next;
        } catch (err) {
            if (!stale()) {
                this.error = extractStudioError(err);
            }
        } finally {
            if (lGen === this.lifecycleGen && pGen === this.previewGen && this.busyAction === 'preview') {
                this.busyAction = prevBusy;
            }
        }
    }

    async loadReadiness(runTests = false): Promise<ReadinessReport | null> {
        const studioId = this.activeId;
        if (!studioId) return null;
        const gen = this.lifecycleGen;
        this.busyAction = 'readiness';
        this.error = null;
        try {
            const report = runTests
                ? await apiRunReadiness(studioId, { run_tests: true }, this.fetcher)
                : await apiGetReadiness(studioId, false, this.fetcher);
            if (gen !== this.lifecycleGen) return null;
            this.readiness = report;
            return report;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return null;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'readiness') this.busyAction = null;
        }
    }

    async runSandboxTests(body: TestSandboxRequest = {}): Promise<SandboxTestReport | null> {
        const studioId = this.activeId;
        if (!studioId) return null;
        const gen = this.lifecycleGen;
        this.busyAction = 'sandbox';
        this.error = null;
        try {
            const report = await apiTestSandbox(studioId, body, this.fetcher);
            if (gen !== this.lifecycleGen) return null;
            this.sandboxResult = report;
            return report;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return null;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'sandbox') this.busyAction = null;
        }
    }

    async installActive(body: InstallWorkspaceRequest = { activate_runtime: true, auto_approve: true }): Promise<InstallWorkspaceResult | null> {
        const studioId = this.activeId;
        if (!studioId) return null;
        const gen = this.lifecycleGen;
        this.busyAction = 'install';
        this.error = null;
        try {
            const res = await apiInstallWorkspace(studioId, body, this.fetcher);
            if (gen !== this.lifecycleGen) return null;
            this.installResult = res;
            await pluginsStore.refresh({ force: true });
            if (gen !== this.lifecycleGen) return null;
            await this.refreshDetail(studioId);
            return gen === this.lifecycleGen ? res : null;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return null;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'install') this.busyAction = null;
        }
    }

    async publishActive(body: PublishWorkspaceRequest): Promise<PublishWorkspaceResult | null> {
        const studioId = this.activeId;
        if (!studioId) return null;
        const gen = this.lifecycleGen;
        this.busyAction = 'publish';
        this.error = null;
        try {
            const res = await apiPublishWorkspace(studioId, body, this.fetcher);
            if (gen !== this.lifecycleGen) return null;
            if (body.dry_run !== false) {
                this.publishPreview = res;
                this.publishResult = null;
            } else {
                this.publishResult = res;
            }
            return res;
        } catch (err) {
            if (gen === this.lifecycleGen) {
                this.error = extractStudioError(err);
            }
            return null;
        } finally {
            if (gen === this.lifecycleGen && this.busyAction === 'publish') this.busyAction = null;
        }
    }

    dispose(): void {
        this.lifecycleGen += 1;
        this.listGen += 1;
        this.detailGen += 1;
        this.previewGen += 1;
        this.loading = false;
        this.busyAction = null;
        this.closeDevStream();
        this.releaseInspectorHandle();
    }

    private clearActiveWorkspace(): void {
        this.lifecycleGen += 1;
        this.listGen += 1;
        this.detailGen += 1;
        this.previewGen += 1;
        this.loading = false;
        this.activeId = null;
        this.detail = null;
        this.readiness = null;
        this.surfaceId = null;
        this.sandboxResult = null;
        this.installResult = null;
        this.previewByTheme = {};
        this.devEvents = [];
        this.resetPublishState();
        this.closeDevStream();
        this.releaseInspectorHandle();
    }

    private syncWorkspaceRow(updated: StudioWorkspace): void {
        const idx = this.workspaces.findIndex((w) => w.studio_id === updated.studio_id);
        if (idx === -1) {
            this.workspaces = [updated, ...this.workspaces];
        } else {
            const next = [...this.workspaces];
            next[idx] = updated;
            this.workspaces = next;
        }
    }

    private syncInspectorLease(pluginId: string, active: boolean): void {
        if (!pluginId || !active) {
            this.releaseInspectorHandle();
            return;
        }
        if (this.inspectorPluginId === pluginId && this.releaseInspector) return;
        this.releaseInspectorHandle();
        this.inspectorPluginId = pluginId;
        this.releaseInspector = pluginsStore.acquireInspector(
            pluginId,
            this.detail?.dev_status?.lease?.install_key ?? null,
        );
    }

    private releaseInspectorHandle(): void {
        this.releaseInspector?.();
        this.releaseInspector = null;
        this.inspectorPluginId = null;
    }

    private syncDevStream(pluginId: string | null): void {
        if (!pluginId) {
            this.closeDevStream();
            return;
        }
        if (this.devStreamPluginId === pluginId && this.devAbort && !this.devAbort.signal.aborted) return;
        this.closeDevStream();
        if (this.fetcher && !this.streamOpener) return;
        if (!this.streamOpener && auth.state === 'signed-out') {
            return;
        }
        const opener: StudioStreamOpener = this.streamOpener ?? authFetchStream;
        const gen = this.lifecycleGen;
        const controller = new AbortController();
        this.devAbort = controller;
        this.devStreamPluginId = pluginId;
        void this.consumeDevStream(pluginId, opener, gen, controller);
    }

    private async consumeDevStream(
        pluginId: string,
        opener: StudioStreamOpener,
        gen: number,
        controller: AbortController,
    ): Promise<void> {
        try {
            const response = await opener(
                `/cplug-owner/dev/stream/${encodeURIComponent(pluginId)}`,
                {
                    method: 'GET',
                    headers: { Accept: 'text/event-stream' },
                    signal: controller.signal,
                },
            );
            if (gen !== this.lifecycleGen || controller !== this.devAbort || controller.signal.aborted) {
                await response.body?.cancel().catch(() => undefined);
                return;
            }
            const reader = response.body?.getReader();
            if (!reader) return;
            const decoder = new TextDecoder();
            let buffer = '';
            while (true) {
                const { value, done } = await reader.read();
                if (gen !== this.lifecycleGen || controller !== this.devAbort || controller.signal.aborted) {
                    await reader.cancel().catch(() => undefined);
                    return;
                }
                if (value) {
                    buffer += decoder.decode(value, { stream: true });
                }
                if (done) {
                    buffer += decoder.decode();
                    buffer = buffer.replace(/\r\n|\r/g, '\n');
                } else if (buffer.endsWith('\r')) {
                    buffer = `${buffer.slice(0, -1).replace(/\r\n|\r/g, '\n')}\r`;
                } else {
                    buffer = buffer.replace(/\r\n|\r/g, '\n');
                }
                let sep = buffer.indexOf('\n\n');
                while (sep !== -1) {
                    const block = buffer.slice(0, sep);
                    buffer = buffer.slice(sep + 2);
                    this.dispatchSseBlock(block, gen, controller);
                    sep = buffer.indexOf('\n\n');
                }
                if (done) {
                    if (buffer.trim()) {
                        this.dispatchSseBlock(buffer, gen, controller);
                    }
                    break;
                }
            }
        } catch {
        }
    }

    private dispatchSseBlock(rawBlock: string, gen: number, controller: AbortController): void {
        if (gen !== this.lifecycleGen || controller !== this.devAbort || controller.signal.aborted) return;
        let eventName = 'message';
        const dataLines: string[] = [];
        for (const line of rawBlock.split('\n')) {
            if (!line || line.startsWith(':')) continue;
            const colon = line.indexOf(':');
            const field = colon === -1 ? line : line.slice(0, colon);
            let value = colon === -1 ? '' : line.slice(colon + 1);
            if (value.startsWith(' ')) value = value.slice(1);
            if (field === 'event') {
                eventName = value || 'message';
            } else if (field === 'data') {
                dataLines.push(value);
            }
        }
        if (!DEV_STREAM_EVENTS.has(eventName) || dataLines.length === 0) return;
        const rawData = dataLines.join('\n');
        let payload: unknown = rawData;
        try {
            payload = JSON.parse(rawData);
        } catch {
            payload = rawData;
        }
        this.devStreamSeq += 1;
        const record: DevStreamRecord = {
            id: `${this.devStreamSeq}`,
            type: eventName,
            payload,
            at: new Date().toISOString(),
        };
        this.devEvents = [record, ...this.devEvents].slice(0, 40);
        if (this.activeId && DEV_STREAM_REFRESH_EVENTS.has(eventName)) {
            void pluginsStore.refresh({ force: true });
            void this.refreshDetail(this.activeId);
        }
    }

    private closeDevStream(): void {
        if (this.devAbort) {
            try {
                this.devAbort.abort();
            } catch {
            }
        }
        this.devAbort = null;
        this.devStreamPluginId = null;
    }
}

export const studioStore = new StudioStore();
