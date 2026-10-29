import type { PublishAccount } from './publish';
import { hostWindow } from '../sessions/env';
import { sessionStore } from '../sessions/store.svelte';
import type { ProjectRow } from '../sessions/types';
import type { RunningSessionRow } from '../sessions/types';
import type {
    CatalogAccountExport,
    CatalogDeleteResult,
    CatalogDeviceSessions,
    CatalogRevoked,
    CatalogAuthSession,
    CatalogIndexState,
    CatalogItem,
    CatalogContents,
    CatalogItemResponse,
    CatalogListResponse,
    DeviceFlowStart,
    EmailFlowStart,
    InstallPreview,
    InstallRequest,
    InstalledItem,
    InstalledListResponse,
    ItemInstalls,
    SkillAutopsy,
    SkillUsage,
    ItemRatings,
    ItemRatingWrite,
    RatingWriteBody,
    OneShotResult,
    PatchInstalledRequest,
    UpdateInstalledRequest,
    ThemePalettesResponse,
} from './types';

export interface CatalogHost {
    listItems(): Promise<CatalogListResponse>;
    refreshIndex(): Promise<CatalogIndexState>;
    opened?(): Promise<unknown>;
    listInstalled(): Promise<InstalledListResponse>;
    contents?(itemId: string): Promise<CatalogContents>;
    themePalettes?(): Promise<ThemePalettesResponse>;
    previewInstall(request: InstallRequest): Promise<InstallPreview>;
    install(request: InstallRequest): Promise<InstalledItem>;
    uninstall(installId: string): Promise<unknown>;
    /* the reading pane */
    item(itemId: string): Promise<CatalogItem | null>;
    patchInstalled(installId: string, body: PatchInstalledRequest): Promise<InstalledItem>;
    applyUpdate(installId: string, body: UpdateInstalledRequest): Promise<InstalledItem>;
    /* running sessions */
    runningSessions(): readonly RunningSessionRow[];
    oneShot(sessionId: string, text: string): Promise<OneShotResult>;
    tryInScratch(prompt: string): Promise<unknown>;
    listProjects(): Promise<ProjectRow[]>;
    currentProjectPath(): Promise<string | null>;
    itemRatings(itemId: string): Promise<ItemRatings>;
    rateItem(itemId: string, body: RatingWriteBody): Promise<ItemRatingWrite>;
    removeRating(itemId: string): Promise<ItemRatingWrite>;
    itemInstalls(itemId: string): Promise<ItemInstalls>;
    installCounts(ids: readonly string[]): Promise<{ items: Record<string, ItemInstalls> }>;
    skillUsage?(skill: string): Promise<SkillUsage>;
    skillAutopsy?(skill: string): Promise<SkillAutopsy>;
    restoreInstalled?(installId: string, body: UpdateInstalledRequest): Promise<InstalledItem>;
    setFork?(installId: string, forked: boolean): Promise<InstalledItem>;
    folderPicker(): (() => Promise<string | null>) | null;
    catalogSession(): Promise<CatalogAuthSession>;
    startDeviceFlow(): Promise<DeviceFlowStart>;
    pollDeviceFlow(flowId: string): Promise<CatalogAuthSession>;
    startGoogleFlow(): Promise<DeviceFlowStart>;
    pollGoogleFlow(flowId: string): Promise<CatalogAuthSession>;
    startEmailFlow(email: string): Promise<EmailFlowStart>;
    verifyEmailCode(flowId: string, code: string): Promise<CatalogAuthSession>;
    verifyGoogleMailboxCode(flowId: string, code: string): Promise<CatalogAuthSession>;
    signOutOfCatalog(): Promise<CatalogAuthSession>;
    listCatalogSessions?(): Promise<CatalogDeviceSessions>;
    revokeCatalogSession?(sid: string): Promise<CatalogRevoked>;
    publishAccount?(): Promise<PublishAccount>;
    sendHero?(body: { kind: string; name: string; image_base64: string }): Promise<{ submission_id?: string }>;
    revokeOtherCatalogSessions?(): Promise<CatalogRevoked>;
    deleteCatalogAccount?(confirm: string): Promise<CatalogDeleteResult>;
    exportCatalogAccount?(): Promise<CatalogAccountExport>;
}

interface LegacyApi {
    getPublishAccount(): Promise<PublishAccount>;
    sendHeroImage(body: { kind: string; name: string; image_base64: string }): Promise<{ submission_id?: string }>;
    getCatalogItems(): Promise<CatalogListResponse>;
    getCatalogItem(itemId: string): Promise<CatalogItemResponse>;
    getCatalogContents(itemId: string): Promise<CatalogContents>;
    call(path: string, init?: Record<string, unknown>): Promise<unknown>;
    patchCatalogInstalled(installId: string, body: PatchInstalledRequest): Promise<InstalledItem>;
    updateCatalogInstalled(installId: string, body: UpdateInstalledRequest): Promise<InstalledItem>;
    oneShotSkill(sessionId: string, text: string): Promise<OneShotResult>;
    createSession(params: Record<string, unknown>): Promise<unknown>;
    refreshCatalogIndex(): Promise<CatalogIndexState>;
    catalogOpened(): Promise<unknown>;
    getCatalogInstalled(): Promise<InstalledListResponse>;
    previewCatalogInstall(request: InstallRequest): Promise<InstallPreview>;
    installCatalogItem(request: InstallRequest): Promise<InstalledItem>;
    uninstallCatalogItem(installId: string): Promise<unknown>;
    getProjects(includeArchived: boolean): Promise<ProjectRow[]>;
    getCurrentSession(): Promise<Record<string, unknown> | null>;
    getSession(sessionId: string): Promise<Record<string, unknown> | null>;
    getCatalogItemRatings(itemId: string): Promise<ItemRatings>;
    putCatalogItemRating(itemId: string, body: RatingWriteBody): Promise<ItemRatingWrite>;
    deleteCatalogItemRating(itemId: string): Promise<ItemRatingWrite>;
    getCatalogItemInstalls(itemId: string): Promise<ItemInstalls>;
    getCatalogInstallCounts(ids: readonly string[]): Promise<{ items: Record<string, ItemInstalls> }>;
    getSkillUsage(skill: string): Promise<SkillUsage>;
    getSkillAutopsy(skill: string): Promise<SkillAutopsy>;
    restoreCatalogInstalled(installId: string, body: UpdateInstalledRequest): Promise<InstalledItem>;
    setCatalogInstalledFork(installId: string, forked: boolean): Promise<InstalledItem>;
    getCatalogSession(): Promise<CatalogAuthSession>;
    startCatalogDeviceFlow(): Promise<DeviceFlowStart>;
    pollCatalogDeviceFlow(flowId: string): Promise<CatalogAuthSession>;
    startCatalogGoogleFlow(): Promise<DeviceFlowStart>;
    pollCatalogGoogleFlow(flowId: string): Promise<CatalogAuthSession>;
    startCatalogEmailFlow(email: string): Promise<EmailFlowStart>;
    verifyCatalogEmailCode(flowId: string, code: string): Promise<CatalogAuthSession>;
    verifyCatalogGoogleMailboxCode(flowId: string, code: string): Promise<CatalogAuthSession>;
    signOutOfCatalog(): Promise<CatalogAuthSession>;
    getCatalogAccountSessions(): Promise<CatalogDeviceSessions>;
    revokeCatalogAccountSession(sid: string): Promise<CatalogRevoked>;
    revokeOtherCatalogSessions(): Promise<CatalogRevoked>;
    deleteCatalogAccount(confirm: string): Promise<CatalogDeleteResult>;
    exportCatalogAccount(): Promise<CatalogAccountExport>;
}

export function workingDirOf(info: Record<string, unknown> | null): string | null {
    if (!info || typeof info !== 'object') return null;
    const session = (info as { session?: Record<string, unknown> | null }).session;
    if (!session || typeof session !== 'object') return null;
    const dir = (session as { working_dir?: unknown }).working_dir;
    return typeof dir === 'string' && dir.trim() ? dir : null;
}

const api = (): LegacyApi =>
    (hostWindow() as unknown as { API: LegacyApi } | undefined)?.API as LegacyApi;

async function viewedProjectPath(): Promise<string | null> {
    const ctl = (hostWindow() as unknown as { TerminalController?: { _sessionId?: () => string | null } } | undefined)
        ?.TerminalController;
    const id = typeof ctl?._sessionId === 'function' ? ctl._sessionId() : null;
    if (!id || !id.trim()) return null;
    try {
        return workingDirOf(await api().getSession(id.trim()));
    } catch (error) {
        console.warn('CloudeWeb: could not read the viewed session', error);
        return null;
    }
}

export function browserCatalogHost(): CatalogHost {
    return {
        listItems: () => api().getCatalogItems(),
        contents: (itemId) => api().getCatalogContents(itemId),
        themePalettes: () => api().call('/catalog/theme-palettes') as Promise<ThemePalettesResponse>,
        refreshIndex: () => api().refreshCatalogIndex(),
        opened: () => api().catalogOpened(),
        listInstalled: () => api().getCatalogInstalled(),
        previewInstall: (request) => api().previewCatalogInstall(request),
        install: (request) => api().installCatalogItem(request),
        uninstall: (installId) => api().uninstallCatalogItem(installId),
        item: async (itemId) => {
            const answer = await api().getCatalogItem(itemId);
            return answer?.item ?? null;
        },
        patchInstalled: (installId, body) => api().patchCatalogInstalled(installId, body),
        applyUpdate: (installId, body) => api().updateCatalogInstalled(installId, body),
        runningSessions: () => sessionStore.runningSessions,
        oneShot: (sessionId, text) => api().oneShotSkill(sessionId, text),
        tryInScratch: (prompt) =>
            api().createSession({ opening_prompt: prompt, auto_start_claude: true }),
        listProjects: () => api().getProjects(false),
        currentProjectPath: viewedProjectPath,
        itemRatings: (itemId) => api().getCatalogItemRatings(itemId),
        rateItem: (itemId, body) => api().putCatalogItemRating(itemId, body),
        removeRating: (itemId) => api().deleteCatalogItemRating(itemId),
        itemInstalls: (itemId) => api().getCatalogItemInstalls(itemId),
        installCounts: (ids) => api().getCatalogInstallCounts(ids),
        skillUsage: (skill) => api().getSkillUsage(skill),
        skillAutopsy: (skill) => api().getSkillAutopsy(skill),
        restoreInstalled: (installId, body) => api().restoreCatalogInstalled(installId, body),
        setFork: (installId, forked) => api().setCatalogInstalledFork(installId, forked),
        folderPicker() {
            const picker = (hostWindow() as unknown as Record<string, unknown> | undefined)
                ?.FolderPickerModal as
                | { open(options?: Record<string, unknown>): Promise<string | null> }
                | undefined;
            if (!picker || typeof picker.open !== 'function') return null;
            return () => picker.open();
        },
        catalogSession: () => api().getCatalogSession(),
        publishAccount: () => api().getPublishAccount(),
        sendHero: (body) => api().sendHeroImage(body),
        startDeviceFlow: () => api().startCatalogDeviceFlow(),
        pollDeviceFlow: (flowId) => api().pollCatalogDeviceFlow(flowId),
        startGoogleFlow: () => api().startCatalogGoogleFlow(),
        pollGoogleFlow: (flowId) => api().pollCatalogGoogleFlow(flowId),
        startEmailFlow: (email) => api().startCatalogEmailFlow(email),
        verifyEmailCode: (flowId, code) => api().verifyCatalogEmailCode(flowId, code),
        verifyGoogleMailboxCode: (flowId, code) =>
            api().verifyCatalogGoogleMailboxCode(flowId, code),
        signOutOfCatalog: () => api().signOutOfCatalog(),
        listCatalogSessions: () => api().getCatalogAccountSessions(),
        revokeCatalogSession: (sid) => api().revokeCatalogAccountSession(sid),
        revokeOtherCatalogSessions: () => api().revokeOtherCatalogSessions(),
        deleteCatalogAccount: (confirm) => api().deleteCatalogAccount(confirm),
        exportCatalogAccount: () => api().exportCatalogAccount(),
    };
}
