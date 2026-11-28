
<script lang="ts">
    import { onMount, tick } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import type { ProfileRow } from '../launch-profiles-page/api';
    import { reasonOf } from '../launchpad/failure-reason';
    import { cloneFailure } from '../../../../client/js/labels/project-create.js';
    import ModalShell from '../dialog-frame/ModalShell.svelte';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { liveWizardApi, loadRecentFolders, type WizardApi } from './api';
    import {
        buildWizardSessionPayload,
        extractRepoName,
        folderBasename,
        initialViewForEntry,
        joinChildPath,
        projectDotRole,
        shortenPath,
        slugifyProjectName,
        splitProjectsAZ,
        type WizardAccount,
        type WizardAdjacentContext,
        type WizardComputer,
        type WizardEntryContext,
        type WizardProject,
        type WizardView,
    } from './model';
    import type { WizardOutcome } from './open';
    import LaunchFields from './LaunchFields.svelte';
    import FolderPickerStep from './FolderPickerStep.svelte';
    import ProjectKindStep from './ProjectKindStep.svelte';
    import CloneProjectStep from './CloneProjectStep.svelte';
    import OpenFolderStep from './OpenFolderStep.svelte';

    type FolderTarget = 'new_project' | 'disposable' | 'clone_project' | 'open_folder';

    interface Props {
        entryContext?: WizardEntryContext;
        adjacent?: WizardAdjacentContext | null;
        initialProject?: WizardProject | null;
        initialAgentName?: string;
        terminalDims?: () => { cols?: number; rows?: number };
        onProjectSaved?: () => void;
        api?: WizardApi;
        t?: Translate;
        close: (value: WizardOutcome | null) => void;
    }

    let {
        entryContext = 'top_plus',
        adjacent = null,
        initialProject = null,
        initialAgentName = '',
        terminalDims = () => ({}),
        onProjectSaved,
        api = liveWizardApi,
        t = reactiveT,
        close,
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    const rootView: WizardView = initialViewForEntry(entryContext, Boolean(initialProject));
    let view = $state<WizardView>(rootView);
    let viewHistory = $state<WizardView[]>([]);
    let stepHost = $state<HTMLElement | null>(null);
    let quickContinue = $state(false);

    $effect(() => {
        const currentView = view;
        void tick().then(() => {
            if (!stepHost) return;
            if (
                currentView === 'existing_pick' ||
                currentView === 'new_setup' ||
                currentView === 'clone_setup' ||
                currentView === 'open_folder_setup'
            ) {
                const input = stepHost.querySelector<HTMLInputElement>('input');
                if (input) {
                    input.focus();
                    return;
                }
            }
            stepHost.focus();
        });
    });
    let folderTarget = $state<FolderTarget>('new_project');

    let loadingBoot = $state(true);
    let projects = $state<WizardProject[]>([]);
    let activeProjectRoots = $state<Set<string>>(new Set());
    let profiles = $state<ProfileRow[]>([]);
    let computers = $state<WizardComputer[]>([{ key: 'local', label: '', online: true }]);
    let accounts = $state<WizardAccount[]>([]);
    let defaultDir = $state('/tmp');
    let homeDir = $state<string | null>(null);
    let recentFolders = $state<string[]>([]);

    let projectQuery = $state('');
    // svelte-ignore state_referenced_locally
    let selectedProject = $state<WizardProject | null>(initialProject);
    // svelte-ignore state_referenced_locally
    let selectedProjectDot = $state<'orange' | 'cyan' | 'yellow' | 'violet' | 'green' | 'muted'>(
        initialProject ? projectDotRole(initialProject.color, true, 0) : 'cyan',
    );
    let isGitRepo = $state(false);
    let useWorktree = $state(false);
    let worktreeBranch = $state('');

    let newProjectName = $state('');
    let newProjectParent = $state('');
    let newProjectNameError = $state('');

    let cloneRepoUrl = $state('');
    let cloneRepoUrlError = $state('');
    let cloneProjectName = $state('');
    let cloneParentDir = $state('');
    let cloneDescription = $state('');

    let openFolderPath = $state('');
    let openFolderError = $state('');
    let openFolderName = $state('');
    let openFolderNameError = $state('');
    let openFolderDescription = $state('');

    let disposableCustomPath = $state<string | null>(null);

    // svelte-ignore state_referenced_locally
    let agentName = $state(initialAgentName);
    let selectedProfileId = $state('');
    let selectedComputerKey = $state('local');
    let model = $state('');
    let selectedAccountId = $state<string | null>(null);
    let storyRef = $state<string | null>(null);
    let moreOpen = $state(false);

    let submitting = $state(false);
    let submitError = $state('');

    onMount(() => {
        if (initialProject) {
            void probeProjectWorktree(initialProject);
        }
        void (async () => {
            try {
                const boot = await api.loadBootstrap();
                projects = boot.projects;
                activeProjectRoots = boot.activeProjectRoots;
                profiles = boot.profiles;
                computers = boot.computers;
                accounts = boot.accounts;
                defaultDir = boot.defaultDir;
                homeDir = boot.homeDir;
                if (!newProjectParent) newProjectParent = boot.defaultDir;
                if (!cloneParentDir) cloneParentDir = boot.defaultDir;
                if (selectedProject) {
                    const normTarget = (selectedProject.path || selectedProject.root || '').replace(/\/+$/, '');
                    const matched = boot.projects.find(
                        (p) =>
                            (selectedProject!.id > 0 && p.id === selectedProject!.id) ||
                            (normTarget && (p.path || p.root || '').replace(/\/+$/, '') === normTarget),
                    );
                    if (matched) {
                        selectedProject = {
                            ...selectedProject,
                            id: matched.id,
                            defaultLaunchProfile: selectedProject.defaultLaunchProfile ?? matched.defaultLaunchProfile,
                            companyId: selectedProject.companyId ?? matched.companyId,
                            color: selectedProject.color ?? matched.color,
                        };
                        selectedProjectDot = projectDotRole(selectedProject.color, true, 0);
                    }
                    selectedProfileId = defaultProfileFor(selectedProject);
                } else if (!selectedProfileId && boot.profiles.length > 0) {
                    selectedProfileId = boot.profiles[0]!.id;
                }
                recentFolders = loadRecentFolders([
                    boot.defaultDir,
                    ...boot.projects.slice(0, 4).map((p) => p.path || p.root).filter(Boolean),
                ]);
            } finally {
                loadingBoot = false;
            }
        })();
    });

    const modalTitle = $derived.by(() => {
        if (entryContext === 'project_start') return t('newagent.project_title');
        if (entryContext === 'clone_project') return t('newagent.clone_title');
        if (entryContext === 'open_folder') return t('newagent.open_folder_title');
        return t('newagent.title');
    });

    const filteredProjects = $derived.by(() => {
        const q = projectQuery.trim().toLowerCase();
        if (!q) return projects;
        return projects.filter(
            (p) => p.name.toLowerCase().includes(q) || (p.path || p.root).toLowerCase().includes(q),
        );
    });

    const splitProjects = $derived(splitProjectsAZ(filteredProjects, activeProjectRoots));

    const newProjectTargetPath = $derived(
        joinChildPath(newProjectParent || defaultDir, slugifyProjectName(newProjectName)),
    );

    const cloneEffectiveName = $derived(
        cloneProjectName.trim() || extractRepoName(cloneRepoUrl) || 'repo',
    );

    const cloneTargetPreviewPath = $derived(
        joinChildPath(cloneParentDir || defaultDir, extractRepoName(cloneRepoUrl) || slugifyProjectName(cloneEffectiveName)),
    );

    const stepBadge = $derived.by(() => {
        if (view === 'folder_picker') return t('newagent.step_folder');
        if (entryContext === 'project_launch' && view === 'existing_launch' && viewHistory.length === 0) {
            return t('newagent.step_launch');
        }
        if (entryContext === 'existing_project_pick') {
            return view === 'existing_pick'
                ? t('newagent.step_of', { step: 1, total: 2 })
                : t('newagent.step_of', { step: 2, total: 2 });
        }
        if (entryContext === 'clone_project') {
            return view === 'clone_setup'
                ? t('newagent.step_of', { step: 1, total: 2 })
                : t('newagent.step_of', { step: 2, total: 2 });
        }
        if (entryContext === 'open_folder') {
            return view === 'open_folder_setup'
                ? t('newagent.step_of', { step: 1, total: 2 })
                : t('newagent.step_of', { step: 2, total: 2 });
        }
        switch (view) {
            case 'step1':
            case 'project_kind':
                return t('newagent.step_one');
            case 'disposable':
                return t('newagent.step_of', { step: 2, total: 2 });
            case 'existing_pick':
            case 'new_setup':
            case 'clone_setup':
            case 'open_folder_setup':
                return t('newagent.step_of', { step: 2, total: 3 });
            case 'existing_launch':
                return quickContinue
                    ? t('newagent.step_of', { step: 2, total: 2 })
                    : t('newagent.step_of', { step: 3, total: 3 });
            case 'new_launch':
            case 'clone_launch':
            case 'open_folder_launch':
                return t('newagent.step_of', { step: 3, total: 3 });
        }
    });

    function navigateTo(next: WizardView): void {
        viewHistory = [...viewHistory, view];
        view = next;
    }

    function defaultProfileFor(project: WizardProject | null): string {
        if (project?.defaultLaunchProfile && profiles.some((p) => p.id === project.defaultLaunchProfile)) {
            return project.defaultLaunchProfile;
        }
        return selectedProfileId || profiles[0]?.id || '';
    }

    function resetLaunchTransient(): void {
        submitError = '';
        moreOpen = false;
        useWorktree = false;
        worktreeBranch = '';
        isGitRepo = false;
        selectedComputerKey = 'local';
        model = '';
        selectedAccountId = null;
        storyRef = null;
    }

    async function probeWorktreeDir(dir: string, guard: () => boolean): Promise<void> {
        if (!dir) return;
        const probe = await api.probeWorktree(dir);
        if (guard()) {
            isGitRepo = probe.isGit;
            if (!worktreeBranch) worktreeBranch = probe.suggestedBranch;
        }
    }

    async function probeProjectWorktree(project: WizardProject): Promise<void> {
        const dir = project.path || project.root;
        await probeWorktreeDir(dir, () => selectedProject?.id === project.id && (selectedProject?.path || selectedProject?.root) === dir);
    }

    function goContinueAdjacent(): void {
        if (!adjacent) return;
        resetLaunchTransient();
        selectedProject = adjacent.project;
        selectedProjectDot = projectDotRole(adjacent.project.color, true, 0);
        selectedProfileId = defaultProfileFor(adjacent.project);
        agentName = '';
        quickContinue = true;
        navigateTo('existing_launch');
        void probeProjectWorktree(adjacent.project);
    }

    function goExistingPick(): void {
        submitError = '';
        projectQuery = '';
        quickContinue = false;
        navigateTo('existing_pick');
    }

    function pickExistingProject(project: WizardProject, inDrawer: boolean, idx: number): void {
        resetLaunchTransient();
        selectedProject = project;
        selectedProjectDot = projectDotRole(project.color, inDrawer, idx);
        selectedProfileId = defaultProfileFor(project);
        agentName = '';
        quickContinue = false;
        navigateTo('existing_launch');
        void probeProjectWorktree(project);
    }

    function goNewSetup(): void {
        submitError = '';
        newProjectNameError = '';
        if (!newProjectParent) newProjectParent = defaultDir;
        navigateTo('new_setup');
    }

    function goNewLaunch(): void {
        if (!newProjectName.trim()) {
            newProjectNameError = t('newagent.project_name_required');
            return;
        }
        newProjectNameError = '';
        resetLaunchTransient();
        agentName = '';
        if (!selectedProfileId && profiles.length > 0) selectedProfileId = profiles[0]!.id;
        navigateTo('new_launch');
    }

    function goCloneSetup(): void {
        submitError = '';
        cloneRepoUrlError = '';
        if (!cloneParentDir) cloneParentDir = defaultDir;
        navigateTo('clone_setup');
    }

    function goCloneLaunch(): void {
        if (!cloneRepoUrl.trim()) {
            cloneRepoUrlError = t('newagent.clone_url_required');
            return;
        }
        cloneRepoUrlError = '';
        resetLaunchTransient();
        agentName = '';
        if (!selectedProfileId && profiles.length > 0) selectedProfileId = profiles[0]!.id;
        navigateTo('clone_launch');
    }

    function goOpenFolderSetup(): void {
        submitError = '';
        openFolderError = '';
        openFolderNameError = '';
        navigateTo('open_folder_setup');
    }

    function goOpenFolderLaunch(): void {
        let ok = true;
        if (!openFolderPath.trim()) {
            openFolderError = t('newagent.open_folder_required');
            ok = false;
        } else {
            openFolderError = '';
        }
        if (!openFolderName.trim()) {
            openFolderNameError = t('newagent.project_name_required');
            ok = false;
        } else {
            openFolderNameError = '';
        }
        if (!ok) return;
        resetLaunchTransient();
        agentName = '';
        if (!selectedProfileId && profiles.length > 0) selectedProfileId = profiles[0]!.id;
        navigateTo('open_folder_launch');
        const dir = openFolderPath.trim();
        void probeWorktreeDir(dir, () => openFolderPath.trim() === dir);
    }

    function goDisposable(): void {
        resetLaunchTransient();
        agentName = '';
        if (!selectedProfileId && profiles.length > 0) selectedProfileId = profiles[0]!.id;
        navigateTo('disposable');
    }

    function openFolderPicker(target: FolderTarget): void {
        folderTarget = target;
        navigateTo('folder_picker');
    }

    function handleFolderPicked(path: string): void {
        if (folderTarget === 'new_project') {
            newProjectParent = path;
        } else if (folderTarget === 'clone_project') {
            cloneParentDir = path;
        } else if (folderTarget === 'open_folder') {
            const prevDefault = folderBasename(openFolderPath);
            openFolderPath = path;
            openFolderError = '';
            if (!openFolderName.trim() || openFolderName.trim() === prevDefault) {
                openFolderName = folderBasename(path);
                openFolderNameError = '';
            }
        } else {
            disposableCustomPath = path;
        }
        recentFolders = api.loadRecentFolders();
        goBack();
    }

    function goBack(): void {
        submitError = '';
        if (viewHistory.length > 0) {
            const prev = viewHistory[viewHistory.length - 1]!;
            viewHistory = viewHistory.slice(0, -1);
            view = prev;
            return;
        }
        view = rootView;
    }

    function handleEscape(): boolean {
        if (view === 'folder_picker') {
            goBack();
            return false;
        }
        return true;
    }

    async function launch(branch: 'existing' | 'new_project' | 'disposable' | 'clone' | 'open_folder'): Promise<void> {
        if (submitting || !selectedProfileId) return;
        submitting = true;
        submitError = '';
        let projectSaved = false;
        let cloneStage = false;

        try {
            let effectiveBranch: 'existing' | 'new_project' | 'disposable' =
                branch === 'clone' || branch === 'open_folder' ? 'existing' : branch;
            let effectiveProject: WizardProject | null = selectedProject;

            if (branch === 'new_project') {
                const pname = newProjectName.trim();
                const targetPath = newProjectTargetPath;
                if (!selectedComputerKey || selectedComputerKey === 'local') {
                    await api.createFolder(targetPath);
                    try {
                        await api.createProject({ name: pname, path: targetPath });
                    } catch (err) {
                        const status = (err as { status?: number })?.status;
                        if (status !== 409) throw err;
                    }
                    projectSaved = true;
                    onProjectSaved?.();
                }
            } else if (branch === 'clone') {
                if (!api.cloneProject) {
                    throw new Error(t('error.server_unreachable'));
                }
                cloneStage = true;
                const cloned = await api.cloneProject({
                    repoUrl: cloneRepoUrl.trim(),
                    parentDir: (cloneParentDir || defaultDir).trim() || undefined,
                    projectName: cloneProjectName.trim() || undefined,
                    description: cloneDescription.trim() || undefined,
                });
                cloneStage = false;
                projectSaved = true;
                onProjectSaved?.();
                effectiveProject = {
                    id: 0,
                    name: cloned.name,
                    path: cloned.path,
                    root: cloned.path,
                    defaultLaunchProfile: null,
                    companyId: null,
                    color: null,
                };
            } else if (branch === 'open_folder') {
                const folder = openFolderPath.trim();
                const name = openFolderName.trim();
                const description = openFolderDescription.trim() || null;
                let savedName = name;
                if (api.saveProjectUnique) {
                    const saved = await api.saveProjectUnique({ name, path: folder, description });
                    savedName = saved.name;
                } else {
                    try {
                        await api.createProject({ name, path: folder, description });
                    } catch (err) {
                        const status = (err as { status?: number })?.status;
                        if (status !== 409) throw err;
                    }
                }
                projectSaved = true;
                onProjectSaved?.();
                effectiveProject = {
                    id: 0,
                    name: savedName,
                    path: folder,
                    root: folder,
                    defaultLaunchProfile: null,
                    companyId: null,
                    color: null,
                };
            }

            const payload = buildWizardSessionPayload({
                branch: effectiveBranch,
                agentName,
                profileId: selectedProfileId,
                model: model.trim() || null,
                computerKey: selectedComputerKey,
                accountId: selectedAccountId,
                storyRef,
                project: effectiveProject,
                newProjectName,
                newProjectPath: newProjectTargetPath,
                disposableCustomPath,
                useWorktree,
                worktreeBranch,
                dims: terminalDims(),
            });

            const session = await api.createSession(payload);
            close({ session });
        } catch (err) {
            const detail = cloneStage ? cloneFailure(err, t) : reasonOf(err, t);
            submitError = projectSaved
                ? t('newagent.project_saved_launch_failed', { reason: detail })
                : detail;
        } finally {
            submitting = false;
        }
    }
</script>

<ModalShell
    look="titlerow"
    width="480px"
    title={modalTitle}
    label={modalTitle}
    dismissable={!submitting}
    escapeGuard={handleEscape}
    onCancel={() => close(null)}
    data-new-agent-wizard
>
    {#snippet headExtra()}
        <div class="naw-head-extra">
            {#if viewHistory.length > 0}
                <Button variant="quiet" size="sm" disabled={submitting} onclick={goBack}>
                    <Icon name="chevron-left" size={12} />
                    <span>{t('newagent.back')}</span>
                </Button>
            {/if}
            <span class="naw-step-badge">{stepBadge}</span>
        </div>
    {/snippet}

    <div class="naw-host" bind:this={stepHost} tabindex="-1">
    {#if view === 'step1'}
        <div class="naw-step">
            <h2 class="naw-heading">
                {entryContext === 'tab_plus' && adjacent ? t('newagent.tab_heading') : t('newagent.where_heading')}
            </h2>

            {#if entryContext === 'tab_plus' && adjacent}
                <div class="naw-choice-list">
                    <div class="naw-choice-item">
                        <Button variant="confirm" size="auto" onclick={goContinueAdjacent}>
                            <span class="naw-choice-inner">
                                <span class="naw-choice-icon naw-choice-icon--featured">
                                    <Icon name="arrow-out" size={14} />
                                </span>
                                <span class="naw-choice-copy">
                                    <span class="naw-choice-title">
                                        {t('newagent.continue_in', { project: adjacent.project.name })}
                                    </span>
                                    <span class="naw-choice-sub">
                                        {t('newagent.same_project_as', { tab: adjacent.tabLabel })}
                                    </span>
                                </span>
                                <span class="naw-choice-arrow naw-choice-arrow--featured">
                                    <Icon name="chevron-right" size={13} />
                                </span>
                            </span>
                        </Button>
                    </div>
                </div>

                <div class="naw-divider">
                    <span>{t('newagent.or_somewhere_else')}</span>
                </div>
            {/if}

            <div class="naw-choice-list">
                <div class="naw-choice-item">
                    <Button variant="secondary" size="auto" onclick={goExistingPick}>
                        <span class="naw-choice-inner">
                            <span class="naw-choice-icon"><Icon name="folder" size={14} /></span>
                            <span class="naw-choice-copy">
                                <span class="naw-choice-title">
                                    {entryContext === 'tab_plus' && adjacent
                                        ? t('newagent.branch_existing_other')
                                        : t('newagent.branch_existing')}
                                </span>
                                <span class="naw-choice-sub">{t('newagent.branch_existing_sub')}</span>
                            </span>
                            <span class="naw-choice-arrow"><Icon name="chevron-right" size={13} /></span>
                        </span>
                    </Button>
                </div>

                <div class="naw-choice-item">
                    <Button variant="secondary" size="auto" onclick={goNewSetup}>
                        <span class="naw-choice-inner">
                            <span class="naw-choice-icon"><Icon name="folder-plus" size={14} /></span>
                            <span class="naw-choice-copy">
                                <span class="naw-choice-title">{t('newagent.branch_new')}</span>
                                <span class="naw-choice-sub">{t('newagent.branch_new_sub')}</span>
                            </span>
                            <span class="naw-choice-arrow"><Icon name="chevron-right" size={13} /></span>
                        </span>
                    </Button>
                </div>

                <div class="naw-choice-item">
                    <Button variant="secondary" size="auto" onclick={goDisposable}>
                        <span class="naw-choice-inner">
                            <span class="naw-choice-icon"><Icon name="terminal" size={14} /></span>
                            <span class="naw-choice-copy">
                                <span class="naw-choice-title">{t('newagent.branch_disposable')}</span>
                                <span class="naw-choice-sub">{t('newagent.branch_disposable_sub')}</span>
                            </span>
                            <span class="naw-choice-arrow"><Icon name="chevron-right" size={13} /></span>
                        </span>
                    </Button>
                </div>
            </div>
        </div>
    {:else if view === 'existing_pick'}
        <div class="naw-step">
            <h2 class="naw-heading">{t('newagent.pick_project_heading')}</h2>

            {#if loadingBoot}
                <div class="naw-empty-box">{t('newagent.loading')}</div>
            {:else if projects.length === 0}
                <div class="naw-empty-box">
                    <div class="naw-empty-title">{t('newagent.no_projects_title')}</div>
                    <p class="naw-empty-sub">{t('newagent.no_projects_sub')}</p>
                    <div class="naw-empty-actions">
                        <Button variant="confirm" size="sm" onclick={goNewSetup}>
                            {t('newagent.start_new_project')}
                        </Button>
                        <Button variant="secondary" size="sm" onclick={goDisposable}>
                            {t('newagent.launch_disposable')}
                        </Button>
                    </div>
                </div>
            {:else}
                <Field
                    variant="search"
                    aria-label={t('newagent.filter_projects')}
                    placeholder={t('newagent.filter_projects_placeholder')}
                    bind:value={projectQuery}
                    clearable
                    clearLabel={t('newagent.clear_filter')}
                    block
                />

                {#if splitProjects.drawer.length === 0 && splitProjects.older.length === 0}
                    <div class="naw-empty-box">
                        <div class="naw-empty-title">{t('newagent.no_matches_title')}</div>
                        <p class="naw-empty-sub">{t('newagent.no_matches_sub', { query: projectQuery.trim() })}</p>
                    </div>
                {:else}
                    <div class="naw-project-scroll">
                        {#if splitProjects.drawer.length > 0}
                            <div class="naw-proj-section">
                                <span class="naw-section-label">{t('newagent.in_agent_drawer')}</span>
                                <div class="naw-proj-list">
                                    {#each splitProjects.drawer as proj, idx (proj.id)}
                                        <div class="naw-proj-row">
                                            <Button
                                                variant="row"
                                                size="auto"
                                                title={shortenPath(proj.path || proj.root, homeDir)}
                                                onclick={() => pickExistingProject(proj, true, idx)}
                                            >
                                                <span class="naw-proj-inner">
                                                    <span class="naw-proj-left">
                                                        <span
                                                            class="naw-proj-dot"
                                                            data-dot={projectDotRole(proj.color, true, idx)}
                                                            aria-hidden="true"
                                                        ></span>
                                                        <span class="naw-proj-name">{proj.name}</span>
                                                    </span>
                                                    <span class="naw-proj-chevron">
                                                        <Icon name="chevron-right" size={12} />
                                                    </span>
                                                </span>
                                            </Button>
                                        </div>
                                    {/each}
                                </div>
                            </div>
                        {/if}

                        {#if splitProjects.older.length > 0}
                            <div class="naw-proj-section">
                                <span class="naw-section-label">{t('newagent.older_projects')}</span>
                                <div class="naw-proj-list">
                                    {#each splitProjects.older as proj, idx (proj.id)}
                                        <div class="naw-proj-row">
                                            <Button
                                                variant="row"
                                                size="auto"
                                                title={shortenPath(proj.path || proj.root, homeDir)}
                                                onclick={() => pickExistingProject(proj, false, idx)}
                                            >
                                                <span class="naw-proj-inner">
                                                    <span class="naw-proj-left">
                                                        <span
                                                            class="naw-proj-dot"
                                                            data-dot="muted"
                                                            aria-hidden="true"
                                                        ></span>
                                                        <span class="naw-proj-name">{proj.name}</span>
                                                    </span>
                                                    <span class="naw-proj-chevron">
                                                        <Icon name="chevron-right" size={12} />
                                                    </span>
                                                </span>
                                            </Button>
                                        </div>
                                    {/each}
                                </div>
                            </div>
                        {/if}
                    </div>
                {/if}
            {/if}
        </div>
    {:else if view === 'existing_launch' && selectedProject}
        <div class="naw-step">
            <div class="naw-title-block">
                <h2 class="naw-heading">{t('newagent.launch_in', { project: selectedProject.name })}</h2>
                <div class="naw-context-line">
                    <span class="naw-proj-dot" data-dot={selectedProjectDot} aria-hidden="true"></span>
                    <span class="naw-context-path" title={selectedProject.path || selectedProject.root}>
                        {shortenPath(selectedProject.path || selectedProject.root, homeDir)}
                    </span>
                </div>
            </div>

            {#if submitError}
                <div class="naw-error" role="alert">{submitError}</div>
            {/if}

            <LaunchFields
                {profiles}
                {selectedProfileId}
                onSelectProfile={(id) => (selectedProfileId = id)}
                bind:agentName
                agentNamePlaceholder={t('newagent.agent_name_placeholder', {
                    sample: `${slugifyProjectName(selectedProject.name)}-fix`,
                })}
                profilesFirst={false}
                {computers}
                {selectedComputerKey}
                onSelectComputer={(key) => (selectedComputerKey = key)}
                bind:model
                {accounts}
                {selectedAccountId}
                onSelectAccount={(id) => (selectedAccountId = id)}
                bind:storyRef
                showWorktree={isGitRepo}
                {useWorktree}
                onToggleWorktree={() => (useWorktree = !useWorktree)}
                bind:worktreeBranch
                {moreOpen}
                onToggleMore={() => (moreOpen = !moreOpen)}
                {t}
            />

            <div class="naw-primary-cta">
                <Button
                    variant="confirm"
                    size="auto"
                    disabled={submitting || !selectedProfileId}
                    onclick={() => launch('existing')}
                >
                    <span class="naw-cta-inner">
                        {submitting ? t('newagent.launching') : t('newagent.launch_btn')}
                    </span>
                </Button>
            </div>
        </div>
    {:else if view === 'new_setup'}
        <div class="naw-step">
            <h2 class="naw-heading">{t('newagent.branch_new')}</h2>

            <Field
                label={t('newagent.project_name_label')}
                placeholder={t('newagent.project_name_placeholder')}
                bind:value={newProjectName}
                error={newProjectNameError || undefined}
                autocomplete="off"
                block
                onkeydown={(e) => {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        goNewLaunch();
                    }
                }}
            />

            <div class="naw-path-group">
                <span class="naw-section-label">{t('newagent.folder_path_label')}</span>
                <div class="naw-path-box">
                    <span class="naw-path-value" title={newProjectParent || defaultDir}>
                        {newProjectParent || defaultDir}
                    </span>
                    <Button variant="secondary" size="sm" onclick={() => openFolderPicker('new_project')}>
                        {t('newagent.browse_folders')}
                    </Button>
                </div>
                <span class="naw-path-hint" title={newProjectTargetPath}>
                    {t('newagent.project_folder_preview', { path: shortenPath(newProjectTargetPath, homeDir) })}
                </span>
            </div>

            <div class="naw-primary-cta">
                <Button variant="confirm" size="auto" onclick={goNewLaunch}>
                    <span class="naw-cta-inner">{t('newagent.continue_btn')}</span>
                </Button>
            </div>

            {#if entryContext !== 'project_start'}
                <div class="naw-alt-links">
                    <span class="naw-alt-label">{t('newagent.or_other_project_ways')}</span>
                    <Button variant="quiet" size="sm" onclick={goCloneSetup}>
                        {t('newagent.kind_clone')}
                    </Button>
                    <Button variant="quiet" size="sm" onclick={goOpenFolderSetup}>
                        {t('newagent.kind_folder')}
                    </Button>
                </div>
            {/if}
        </div>
    {:else if view === 'project_kind'}
        <ProjectKindStep
            onEmpty={goNewSetup}
            onClone={goCloneSetup}
            onOpenFolder={goOpenFolderSetup}
            {t}
        />
    {:else if view === 'clone_setup'}
        <CloneProjectStep
            bind:repoUrl={cloneRepoUrl}
            repoUrlError={cloneRepoUrlError}
            bind:projectName={cloneProjectName}
            parentDir={cloneParentDir}
            bind:description={cloneDescription}
            {defaultDir}
            {homeDir}
            onBrowse={() => openFolderPicker('clone_project')}
            onContinue={goCloneLaunch}
            {t}
        />
    {:else if view === 'clone_launch'}
        <div class="naw-step">
            <div class="naw-title-block">
                <h2 class="naw-heading">{t('newagent.launch_in', { project: cloneEffectiveName })}</h2>
                <span class="naw-context-path" title={cloneTargetPreviewPath}>
                    {shortenPath(cloneTargetPreviewPath, homeDir)}
                </span>
            </div>

            {#if submitError}
                <div class="naw-error" role="alert">{submitError}</div>
            {/if}

            <LaunchFields
                {profiles}
                {selectedProfileId}
                onSelectProfile={(id) => (selectedProfileId = id)}
                bind:agentName
                agentNamePlaceholder={t('newagent.agent_name_placeholder', {
                    sample: `${slugifyProjectName(cloneEffectiveName)}-init`,
                })}
                profilesFirst={false}
                {computers}
                {selectedComputerKey}
                onSelectComputer={(key) => (selectedComputerKey = key)}
                bind:model
                {accounts}
                {selectedAccountId}
                onSelectAccount={(id) => (selectedAccountId = id)}
                bind:storyRef
                showWorktree={false}
                {moreOpen}
                onToggleMore={() => (moreOpen = !moreOpen)}
                {t}
            />

            <div class="naw-primary-cta">
                <Button
                    variant="confirm"
                    size="auto"
                    disabled={submitting || !selectedProfileId}
                    onclick={() => launch('clone')}
                >
                    <span class="naw-cta-inner">
                        {submitting ? t('newagent.cloning') : t('newagent.clone_and_launch_btn')}
                    </span>
                </Button>
            </div>
        </div>
    {:else if view === 'open_folder_setup'}
        <OpenFolderStep
            folderPath={openFolderPath}
            folderError={openFolderError}
            bind:projectName={openFolderName}
            projectNameError={openFolderNameError}
            bind:description={openFolderDescription}
            {homeDir}
            onBrowse={() => openFolderPicker('open_folder')}
            onContinue={goOpenFolderLaunch}
            {t}
        />
    {:else if view === 'open_folder_launch'}
        <div class="naw-step">
            <div class="naw-title-block">
                <h2 class="naw-heading">{t('newagent.launch_in', { project: openFolderName.trim() })}</h2>
                <span class="naw-context-path" title={openFolderPath}>
                    {shortenPath(openFolderPath, homeDir)}
                </span>
            </div>

            {#if submitError}
                <div class="naw-error" role="alert">{submitError}</div>
            {/if}

            <LaunchFields
                {profiles}
                {selectedProfileId}
                onSelectProfile={(id) => (selectedProfileId = id)}
                bind:agentName
                agentNamePlaceholder={t('newagent.agent_name_placeholder', {
                    sample: `${slugifyProjectName(openFolderName)}-dev`,
                })}
                profilesFirst={false}
                {computers}
                {selectedComputerKey}
                onSelectComputer={(key) => (selectedComputerKey = key)}
                bind:model
                {accounts}
                {selectedAccountId}
                onSelectAccount={(id) => (selectedAccountId = id)}
                bind:storyRef
                showWorktree={isGitRepo}
                {useWorktree}
                onToggleWorktree={() => (useWorktree = !useWorktree)}
                bind:worktreeBranch
                {moreOpen}
                onToggleMore={() => (moreOpen = !moreOpen)}
                {t}
            />

            <div class="naw-primary-cta">
                <Button
                    variant="confirm"
                    size="auto"
                    disabled={submitting || !selectedProfileId}
                    onclick={() => launch('open_folder')}
                >
                    <span class="naw-cta-inner">
                        {submitting ? t('newagent.launching') : t('newagent.add_and_launch_btn')}
                    </span>
                </Button>
            </div>
        </div>
    {:else if view === 'new_launch'}
        <div class="naw-step">
            <div class="naw-title-block">
                <h2 class="naw-heading">{t('newagent.launch_in', { project: newProjectName.trim() })}</h2>
                <span class="naw-context-path" title={newProjectTargetPath}>
                    {shortenPath(newProjectTargetPath, homeDir)}
                </span>
            </div>

            {#if submitError}
                <div class="naw-error" role="alert">{submitError}</div>
            {/if}

            <LaunchFields
                {profiles}
                {selectedProfileId}
                onSelectProfile={(id) => (selectedProfileId = id)}
                bind:agentName
                agentNamePlaceholder={t('newagent.agent_name_placeholder', {
                    sample: `${slugifyProjectName(newProjectName)}-init`,
                })}
                profilesFirst={false}
                {computers}
                {selectedComputerKey}
                onSelectComputer={(key) => (selectedComputerKey = key)}
                bind:model
                {accounts}
                {selectedAccountId}
                onSelectAccount={(id) => (selectedAccountId = id)}
                bind:storyRef
                showWorktree={false}
                {moreOpen}
                onToggleMore={() => (moreOpen = !moreOpen)}
                {t}
            />

            <div class="naw-primary-cta">
                <Button
                    variant="confirm"
                    size="auto"
                    disabled={submitting || !selectedProfileId}
                    onclick={() => launch('new_project')}
                >
                    <span class="naw-cta-inner">
                        {submitting ? t('newagent.launching') : t('newagent.create_and_launch_btn')}
                    </span>
                </Button>
            </div>
        </div>
    {:else if view === 'disposable'}
        <div class="naw-step">
            <h2 class="naw-heading">{t('newagent.branch_disposable')}</h2>

            {#if submitError}
                <div class="naw-error" role="alert">{submitError}</div>
            {/if}

            <LaunchFields
                {profiles}
                {selectedProfileId}
                onSelectProfile={(id) => (selectedProfileId = id)}
                bind:agentName
                agentNamePlaceholder={t('newagent.agent_name_scratch_placeholder')}
                profilesFirst={true}
                {computers}
                {selectedComputerKey}
                onSelectComputer={(key) => (selectedComputerKey = key)}
                bind:model
                {accounts}
                {selectedAccountId}
                onSelectAccount={(id) => (selectedAccountId = id)}
                bind:storyRef
                showWorktree={false}
                {moreOpen}
                onToggleMore={() => (moreOpen = !moreOpen)}
                {t}
            >
                {#snippet betweenFields()}
                    <div class="naw-path-group">
                        <span class="naw-section-label">{t('newagent.folder_path_label')}</span>
                        <div class="naw-path-box">
                            <span
                                class="naw-path-value"
                                title={disposableCustomPath || t('newagent.tmp_default_display')}
                            >
                                {disposableCustomPath
                                    ? shortenPath(disposableCustomPath, homeDir)
                                    : t('newagent.tmp_default_display')}
                            </span>
                            <Button variant="secondary" size="sm" onclick={() => openFolderPicker('disposable')}>
                                {t('newagent.change_path')}
                            </Button>
                        </div>
                        <div class="naw-path-meta">
                            <span class="naw-path-hint">
                                {disposableCustomPath ? t('newagent.custom_path_hint') : t('newagent.tmp_hint')}
                            </span>
                            {#if disposableCustomPath}
                                <Button
                                    variant="quiet"
                                    size="sm"
                                    onclick={() => (disposableCustomPath = null)}
                                >
                                    {t('newagent.reset_tmp')}
                                </Button>
                            {/if}
                        </div>
                    </div>
                {/snippet}
            </LaunchFields>

            <div class="naw-primary-cta">
                <Button
                    variant="confirm"
                    size="auto"
                    disabled={submitting || !selectedProfileId}
                    onclick={() => launch('disposable')}
                >
                    <span class="naw-cta-inner">
                        {submitting ? t('newagent.launching') : t('newagent.launch_btn')}
                    </span>
                </Button>
            </div>
        </div>
    {:else if view === 'folder_picker'}
        <FolderPickerStep
            initialDir={folderTarget === 'new_project'
                ? newProjectParent || defaultDir
                : folderTarget === 'clone_project'
                  ? cloneParentDir || defaultDir
                  : folderTarget === 'open_folder'
                    ? openFolderPath || defaultDir
                    : disposableCustomPath || defaultDir}
            {homeDir}
            {recentFolders}
            {api}
            {t}
            onSelect={handleFolderPicked}
            onCancel={goBack}
        />
    {/if}
    </div>
</ModalShell>

<style>
    @layer components {
        .naw-host {
            outline: none;
        }

        .naw-head-extra {
            display: inline-flex;
            align-items: center;
            gap: var(--oc-space-2);
            margin-left: auto;
        }

        .naw-step-badge {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
            white-space: nowrap;
        }

        .naw-step {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-4);
            padding: var(--oc-space-2) var(--oc-space-2) var(--oc-space-5);
        }

        .naw-title-block {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1);
            min-width: 0;
        }

        .naw-heading {
            margin: 0;
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-heading);
            line-height: var(--oc-lh-tight);
        }

        .naw-context-line {
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .naw-context-path {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-choice-list {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-3);
        }

        .naw-choice-item {
            display: flex;
            flex-direction: column;
            align-items: stretch;
        }

        .naw-choice-inner {
            width: 100%;
            display: flex;
            align-items: center;
            gap: var(--oc-space-3);
            padding: var(--oc-space-2) var(--oc-space-1);
            text-align: left;
            min-width: 0;
        }

        .naw-choice-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-ground-field);
            color: var(--oc-text-secondary);
            flex-shrink: 0;
        }

        .naw-choice-icon--featured {
            border-color: var(--oc-orange);
            color: var(--oc-orange);
        }

        .naw-choice-copy {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-0-5);
            flex: 1;
            min-width: 0;
        }

        .naw-choice-title {
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-run-title);
            line-height: var(--oc-lh-tight);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-choice-sub {
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
            font-weight: normal;
            line-height: var(--oc-lh-body);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-choice-arrow {
            color: var(--oc-text-muted);
            display: inline-flex;
            align-items: center;
            flex-shrink: 0;
        }

        .naw-choice-arrow--featured {
            color: var(--oc-orange);
        }

        .naw-divider {
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
            margin: var(--oc-space-1) 0;
        }

        .naw-divider::before,
        .naw-divider::after {
            content: '';
            flex: 1;
            height: var(--oc-border);
            background: var(--oc-line-rule);
        }

        .naw-project-scroll {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-4);
            max-height: 360px;
            overflow-y: auto;
        }

        .naw-proj-section {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
        }

        .naw-section-label {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-micro);
            letter-spacing: var(--oc-tracking-caps);
            text-transform: uppercase;
        }

        .naw-proj-list {
            display: flex;
            flex-direction: column;
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-surface-1);
            overflow: hidden;
        }

        .naw-proj-row {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            border-bottom: var(--oc-border) solid var(--oc-line-rule);
        }

        .naw-proj-row:last-child {
            border-bottom: 0;
        }

        .naw-proj-inner {
            width: 100%;
            min-height: 38px;
            padding: var(--oc-space-2) var(--oc-space-3);
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            min-width: 0;
        }

        .naw-proj-left {
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            min-width: 0;
            flex: 1;
            text-align: left;
        }

        .naw-proj-dot {
            width: 8px;
            height: 8px;
            border-radius: var(--oc-radius-round);
            background: var(--oc-text-muted);
            flex-shrink: 0;
        }

        .naw-proj-dot[data-dot='orange'] {
            background: var(--oc-orange);
        }

        .naw-proj-dot[data-dot='cyan'] {
            background: var(--oc-cyan);
        }

        .naw-proj-dot[data-dot='yellow'] {
            background: var(--oc-yellow);
        }

        .naw-proj-dot[data-dot='violet'] {
            background: var(--oc-violet);
        }

        .naw-proj-dot[data-dot='green'] {
            background: var(--oc-green);
        }

        .naw-proj-dot[data-dot='muted'] {
            background: var(--oc-text-muted);
        }

        .naw-proj-name {
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-control);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
        }

        .naw-proj-chevron {
            color: var(--oc-text-muted);
            display: inline-flex;
            align-items: center;
            flex-shrink: 0;
        }

        .naw-empty-box {
            padding: var(--oc-space-5) var(--oc-space-4);
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-surface-1);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: var(--oc-space-3);
            text-align: center;
        }

        .naw-empty-title {
            color: var(--oc-text-bright);
            font-size: var(--oc-fs-run-title);
        }

        .naw-empty-sub {
            margin: 0;
            color: var(--oc-text-secondary);
            font-size: var(--oc-fs-label);
        }

        .naw-empty-actions {
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: var(--oc-space-2);
            padding-top: var(--oc-space-1);
        }

        .naw-path-group {
            display: flex;
            flex-direction: column;
            gap: var(--oc-space-1-5);
        }

        .naw-path-box {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
            padding: var(--oc-space-1-5) var(--oc-space-2) var(--oc-space-1-5) var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-line-panel);
            border-radius: var(--oc-radius-control);
            background: var(--oc-ground-field);
            min-width: 0;
        }

        .naw-path-value {
            color: var(--oc-text-primary);
            font-size: var(--oc-fs-body);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            min-width: 0;
            flex: 1;
        }

        .naw-path-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: var(--oc-space-2);
        }

        .naw-path-hint {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .naw-error {
            padding: var(--oc-space-3);
            border: var(--oc-border) solid var(--oc-coral);
            border-radius: var(--oc-radius-control);
            background: color-mix(in oklab, var(--oc-coral) 14%, transparent);
            color: var(--oc-coral);
            font-size: var(--oc-fs-label);
        }

        .naw-primary-cta {
            display: flex;
            flex-direction: column;
            align-items: stretch;
            padding-top: var(--oc-space-1);
        }

        .naw-cta-inner {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 28px;
            padding: var(--oc-space-1) var(--oc-space-2);
            font-size: var(--oc-fs-control);
        }

        .naw-alt-links {
            display: flex;
            align-items: center;
            justify-content: center;
            flex-wrap: wrap;
            gap: var(--oc-space-1-5);
            padding-top: var(--oc-space-1);
            border-top: var(--oc-border) solid var(--oc-line-rule);
        }

        .naw-alt-label {
            color: var(--oc-text-muted);
            font-size: var(--oc-fs-label);
        }
    }
</style>
