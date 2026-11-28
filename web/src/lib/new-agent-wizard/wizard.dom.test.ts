// @vitest-environment jsdom
import { mount, unmount } from 'svelte';
import { flushSync } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import NewAgentWizardModal from './NewAgentWizardModal.svelte';
import type { WizardApi, WizardBootstrap } from './api';
import type { ProfileRow } from '../launch-profiles-page/api';
import type { WizardProject } from './model';

function mkProfile(id: string, label: string, harness = 'claude'): ProfileRow {
    return {
        id,
        label,
        harness,
        command: harness,
        args: [],
        env: {},
        icon: `logo-${harness}`,
        builtin: true,
        installed: true,
        model: { mode: 'default', value: null },
        account: { mode: 'active', value: null },
    } as unknown as ProfileRow;
}

function fakeBoot(overrides: Partial<WizardBootstrap> = {}): WizardBootstrap {
    return {
        projects: [
            {
                id: 1,
                name: 'carnivore',
                path: '/Users/demo/dev/carnivore',
                root: '/Users/demo/dev/carnivore',
                defaultLaunchProfile: 'codex-yolo',
                companyId: null,
                color: 'cyan',
            },
        ],
        activeProjectRoots: new Set(['/Users/demo/dev/carnivore']),
        profiles: [mkProfile('claude-default', 'Claude', 'claude'), mkProfile('codex-yolo', 'Codex', 'codex')],
        computers: [{ key: 'local', label: '', online: true }],
        accounts: [],
        defaultDir: '/Users/demo/dev',
        homeDir: '/Users/demo',
        ...overrides,
    };
}

function fakeApi(overrides: Partial<WizardApi> = {}): WizardApi {
    return {
        loadBootstrap: vi.fn(async () => fakeBoot()),
        browseFolder: vi.fn(async (p?: string) => ({
            path: p || '/Users/demo/dev',
            parent: '/Users/demo',
            entries: [{ name: 'existing-app', path: '/Users/demo/dev/existing-app' }],
        })),
        createFolder: vi.fn(async (p: string) => ({ path: p, parent: '/Users/demo/dev', entries: [] })),
        probeWorktree: vi.fn(async () => ({ isGit: true, suggestedBranch: 'feat/test' })),
        createProject: vi.fn(async () => {}),
        saveProjectUnique: vi.fn(async (row) => ({ name: row.name, path: row.path })),
        cloneProject: vi.fn(async (p) => ({
            name: p.projectName || 'demo-repo',
            path: `${p.parentDir || '/Users/demo/dev'}/demo-repo`,
        })),
        createSession: vi.fn(async (payload) => ({
            id: 'ses_new',
            tmux_session: 'carnivore_demo',
            working_dir: String(payload.working_dir || ''),
        })),
        loadRecentFolders: vi.fn(() => ['/Users/demo/dev']),
        rememberRecentFolder: vi.fn(),
        ...overrides,
    };
}

const t = (key: string, params?: Record<string, unknown>) =>
    params ? `${key}:${JSON.stringify(params)}` : key;

const mounted: Array<{ instance: Record<string, unknown>; target: HTMLElement }> = [];

function mountWizard(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const instance = mount(NewAgentWizardModal as never, { target, props }) as Record<string, unknown>;
    mounted.push({ instance, target });
    return target;
}

async function settle(): Promise<void> {
    await new Promise((r) => setTimeout(r, 0));
    flushSync();
}

afterEach(() => {
    while (mounted.length > 0) {
        const entry = mounted.pop()!;
        unmount(entry.instance);
        entry.target.remove();
    }
});

describe('NewAgentWizardModal wired entry points (#3403)', () => {
    test('project_start opens project_kind with 3 cards and completes clone_setup -> clone_launch', async () => {
        const api = fakeApi();
        const close = vi.fn();
        const onProjectSaved = vi.fn();
        const root = mountWizard({ entryContext: 'project_start', api, t, close, onProjectSaved });
        await settle();

        expect(root.textContent).toContain('newagent.project_kind_heading');
        expect(root.textContent).toContain('newagent.kind_empty');
        expect(root.textContent).toContain('newagent.kind_clone');
        expect(root.textContent).toContain('newagent.kind_folder');

        const cloneCard = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.kind_clone'),
        )!;
        cloneCard.click();
        flushSync();
        expect(root.textContent).toContain('newagent.clone_heading');

        const urlInput = root.querySelector<HTMLInputElement>('input')!;
        urlInput.value = 'acme-org/demo-repo';
        urlInput.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();

        const cont = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.continue_btn'),
        )!;
        cont.click();
        flushSync();
        expect(root.textContent).toContain('newagent.clone_and_launch_btn');

        const go = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.clone_and_launch_btn'),
        )!;
        go.click();
        await settle();

        expect(api.cloneProject).toHaveBeenCalledWith({
            repoUrl: 'acme-org/demo-repo',
            parentDir: '/Users/demo/dev',
            projectName: undefined,
            description: undefined,
        });
        expect(onProjectSaved).toHaveBeenCalledTimes(1);
        expect(api.createSession).toHaveBeenCalledWith(
            expect.objectContaining({
                project_name: 'demo-repo',
                working_dir: '/Users/demo/dev/demo-repo',
                agent_type: 'claude-default',
            }),
        );
        expect(close).toHaveBeenCalledWith({
            session: expect.objectContaining({ id: 'ses_new' }),
        });
    });

    test('open_folder uses inline FolderPickerStep, auto-fills name, saves project, and launches', async () => {
        const api = fakeApi();
        const close = vi.fn();
        const root = mountWizard({ entryContext: 'open_folder', api, t, close });
        await settle();

        expect(root.textContent).toContain('newagent.open_folder_heading');
        const browseBtn = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.browse_folders'),
        )!;
        browseBtn.click();
        await settle();

        const subRow = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('existing-app'),
        )!;
        subRow.click();
        await settle();

        const useBtn = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.use_folder_btn'),
        )!;
        useBtn.click();
        flushSync();

        const nameInput = root.querySelector<HTMLInputElement>('input')!;
        expect(nameInput.value).toBe('existing-app');

        const cont = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.continue_btn'),
        )!;
        cont.click();
        await settle();

        const addBtn = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.add_and_launch_btn'),
        )!;
        addBtn.click();
        await settle();

        expect(api.saveProjectUnique).toHaveBeenCalledWith({
            name: 'existing-app',
            path: '/Users/demo/dev/existing-app',
            description: null,
        });
        expect(api.createSession).toHaveBeenCalledWith(
            expect.objectContaining({
                project_name: 'existing-app',
                working_dir: '/Users/demo/dev/existing-app',
            }),
        );
        expect(close).toHaveBeenCalledWith({
            session: expect.objectContaining({ id: 'ses_new' }),
        });
    });

    test('project_launch opens directly on existing_launch, hydrates project default profile, and hides back button', async () => {
        const api = fakeApi();
        const close = vi.fn();
        const initialProject: WizardProject = {
            id: 0,
            name: 'carnivore',
            path: '/Users/demo/dev/carnivore',
            root: '/Users/demo/dev/carnivore',
            defaultLaunchProfile: null,
            companyId: null,
            color: null,
        };
        const root = mountWizard({
            entryContext: 'project_launch',
            initialProject,
            initialAgentName: 'carnivore 2',
            api,
            t,
            close,
        });
        await settle();

        expect(root.textContent).toContain('newagent.launch_in');
        expect(root.textContent).not.toContain('newagent.back');
        const codexBtn = root.querySelector<HTMLButtonElement>('[data-profile-id="codex-yolo"]');
        expect(codexBtn?.getAttribute('aria-pressed')).toBe('true');

        const go = [...root.querySelectorAll('button')].find((b) =>
            b.textContent?.includes('newagent.launch_btn'),
        )!;
        go.click();
        await settle();

        expect(api.createSession).toHaveBeenCalledWith(
            expect.objectContaining({
                project_name: 'carnivore',
                working_dir: '/Users/demo/dev/carnivore',
                label: 'carnivore 2',
                agent_type: 'codex-yolo',
            }),
        );
    });

    test('existing_project_pick opens directly on project picker without step 1', async () => {
        const api = fakeApi();
        const close = vi.fn();
        const root = mountWizard({ entryContext: 'existing_project_pick', api, t, close });
        await settle();

        expect(root.textContent).toContain('newagent.pick_project_heading');
        expect(root.textContent).not.toContain('newagent.back');
        expect(root.textContent).toContain('carnivore');
    });
});
