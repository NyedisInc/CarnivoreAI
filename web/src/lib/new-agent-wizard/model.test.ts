import { describe, expect, test } from 'vitest';
import type { ProfileRow } from '../launch-profiles-page/api';
import {
    brandColorRole,
    buildBreadcrumbs,
    buildWizardSessionPayload,
    extractRepoName,
    filterProfilesForWizard,
    folderBasename,
    initialViewForEntry,
    joinChildPath,
    projectDotRole,
    projectToWizardProject,
    shortenPath,
    slugifyProjectName,
    splitProjectsAZ,
    type WizardProject,
} from './model';

function mkProfile(overrides: Partial<ProfileRow>): ProfileRow {
    return {
        id: 'claude-default',
        label: 'Claude Default',
        harness: 'claude',
        command: 'claude',
        args: [],
        env: {},
        icon: 'logo-claude',
        builtin: true,
        installed: true,
        model: { mode: 'default', value: null },
        account: { mode: 'active', value: null },
        ...overrides,
    } as ProfileRow;
}

describe('new-agent-wizard pure model (#3375)', () => {
    test('m1.2 & m1.3: keeps installed non-shell profiles and drops Plain Shell and uninstalled profiles', () => {
        const profiles = [
            mkProfile({ id: 'claude-default', harness: 'claude', installed: true }),
            mkProfile({ id: 'codex-yolo', harness: 'codex', installed: true }),
            mkProfile({ id: 'agy-neon', harness: 'local', icon: 'logo-antigravity', installed: true }),
            mkProfile({ id: 'shell-default', harness: 'shell', installed: true }),
            mkProfile({ id: 'copilot-missing', harness: 'local', icon: 'logo-copilot', installed: false }),
        ];
        const kept = filterProfilesForWizard(profiles);
        expect(kept.map((p) => p.id)).toEqual(['claude-default', 'codex-yolo', 'agy-neon']);
    });

    test('m1.1: maps monochrome harnesses to brand --oc-* roles and preserves native colored SVGs', () => {
        expect(brandColorRole('claude', 'logo-claude')).toBe('');
        expect(brandColorRole('local', 'logo-antigravity')).toBe('');
        expect(brandColorRole('openclaw', 'logo-openclaw')).toBe('');
        expect(brandColorRole('codex', 'logo-codex')).toBe('green');
        expect(brandColorRole('local', 'logo-copilot')).toBe('violet');
        expect(brandColorRole('hermes', 'logo-hermes')).toBe('yellow');
        expect(brandColorRole('local', 'terminal')).toBe('cyan');
        expect(projectDotRole('cyan', true, 0)).toBe('cyan');
        expect(projectDotRole('coral', true, 0)).toBe('orange');
        expect(projectDotRole(null, true, 1)).toBe('violet');
        expect(projectDotRole('orange', false, 0)).toBe('muted');
    });

    test('splits projects into IN AGENT DRAWER and OLDER PROJECTS, both strictly A-Z', () => {
        const projects: WizardProject[] = [
            { id: 1, name: 'zeta', path: '/Users/a/zeta', root: '/Users/a/zeta', defaultLaunchProfile: null, companyId: null },
            { id: 2, name: 'Beta', path: '/Users/a/beta', root: '/Users/a/beta', defaultLaunchProfile: null, companyId: null },
            { id: 3, name: 'alpha', path: '/Users/a/alpha', root: '/Users/a/alpha', defaultLaunchProfile: null, companyId: null },
            { id: 4, name: 'gamma', path: '/Users/a/gamma', root: '/Users/a/gamma', defaultLaunchProfile: null, companyId: null },
        ];
        const active = new Set(['/Users/a/zeta', '/Users/a/beta']);
        const { drawer, older } = splitProjectsAZ(projects, active);
        expect(drawer.map((p) => p.name)).toEqual(['Beta', 'zeta']);
        expect(older.map((p) => p.name)).toEqual(['alpha', 'gamma']);
    });

    test('slugifyProjectName, joinChildPath, shortenPath, and buildBreadcrumbs', () => {
        expect(slugifyProjectName('Billing API v2!')).toBe('billing-api-v2');
        expect(slugifyProjectName('   ')).toBe('new-project');
        expect(joinChildPath('/Users/demo/dev/', '/billing-api')).toBe('/Users/demo/dev/billing-api');
        expect(shortenPath('/Users/demo/dev/api', '/Users/demo')).toBe('~/dev/api');
        expect(shortenPath('/tmp/scratch', '/Users/demo')).toBe('/tmp/scratch');
        expect(buildBreadcrumbs('/Users/demo/dev/api', 'home', '/Users/demo')).toEqual([
            { label: 'home', path: '/Users/demo' },
            { label: 'dev', path: '/Users/demo/dev' },
            { label: 'api', path: '/Users/demo/dev/api' },
        ]);
        expect(buildBreadcrumbs('/tmp/work', 'home', '/Users/demo')).toEqual([
            { label: '/', path: '/' },
            { label: 'tmp', path: '/tmp' },
            { label: 'work', path: '/tmp/work' },
        ]);
    });

    test('buildWizardSessionPayload builds disposable, existing (with worktree), and new_project payloads', () => {
        const disposableDefault = buildWizardSessionPayload({
            branch: 'disposable',
            agentName: 'quick-check',
            profileId: 'claude-default',
            model: null,
            computerKey: 'local',
            accountId: null,
            project: null,
            newProjectName: '',
            newProjectPath: '',
            disposableCustomPath: null,
            useWorktree: false,
            worktreeBranch: '',
            dims: { cols: 120, rows: 40 },
        });
        expect(disposableDefault).toEqual({
            auto_start_claude: true,
            copy_templates: false,
            agent_type: 'claude-default',
            cols: 120,
            rows: 40,
            label: 'quick-check',
            disposable: true,
            project_name: 'Disposable',
        });

        const existingWithWorktree = buildWizardSessionPayload({
            branch: 'existing',
            agentName: '',
            profileId: 'codex-yolo',
            model: 'o3',
            computerKey: 'local',
            accountId: 'acct-1',
            storyRef: 'proj-42',
            project: {
                id: 7,
                name: 'carnivore',
                path: '/Users/demo/carnivore',
                root: '/Users/demo/carnivore',
                defaultLaunchProfile: null,
                companyId: null,
            },
            newProjectName: '',
            newProjectPath: '',
            disposableCustomPath: null,
            useWorktree: true,
            worktreeBranch: 'feat/wizard',
            dims: {},
        });
        expect(existingWithWorktree).toEqual({
            auto_start_claude: true,
            copy_templates: false,
            agent_type: 'codex-yolo',
            model: 'o3',
            account_id: 'acct-1',
            story_ref: 'proj-42',
            project_name: 'carnivore',
            working_dir: '/Users/demo/carnivore',
            worktree: { branch: 'feat/wizard' },
        });

        const newProj = buildWizardSessionPayload({
            branch: 'new_project',
            agentName: '',
            profileId: 'agy-neon',
            model: null,
            computerKey: 'local',
            accountId: null,
            project: null,
            newProjectName: 'billing-api',
            newProjectPath: '/Users/demo/dev/billing-api',
            disposableCustomPath: null,
            useWorktree: false,
            worktreeBranch: '',
            dims: {},
        });
        expect(newProj).toEqual({
            auto_start_claude: true,
            copy_templates: true,
            agent_type: 'agy-neon',
            project_name: 'billing-api',
            label: 'billing-api',
            working_dir: '/Users/demo/dev/billing-api',
        });
    });

    test('#3403: initialViewForEntry, extractRepoName, folderBasename, and projectToWizardProject', () => {
        expect(initialViewForEntry('top_plus')).toBe('step1');
        expect(initialViewForEntry('tab_plus')).toBe('step1');
        expect(initialViewForEntry('project_start')).toBe('project_kind');
        expect(initialViewForEntry('clone_project')).toBe('clone_setup');
        expect(initialViewForEntry('open_folder')).toBe('open_folder_setup');
        expect(initialViewForEntry('existing_project_pick')).toBe('existing_pick');
        expect(initialViewForEntry('project_launch', true)).toBe('existing_launch');
        expect(initialViewForEntry('project_launch', false)).toBe('existing_pick');

        expect(extractRepoName('acme-org/CarnivoreAIDev')).toBe('CarnivoreAIDev');
        expect(extractRepoName('https://github.com/acme-org/CarnivoreAIDev.git')).toBe('CarnivoreAIDev');
        expect(extractRepoName('git@github.com:acme-org/my-repo.git')).toBe('my-repo');
        expect(extractRepoName('just-a-word')).toBeNull();
        expect(extractRepoName('')).toBeNull();

        expect(folderBasename('/Users/demo/dev/billing-api/')).toBe('billing-api');
        expect(folderBasename('')).toBe('');

        expect(
            projectToWizardProject({
                id: 9,
                name: 'api',
                path: '/Users/demo/dev/api',
                default_launch_profile: 'codex-yolo',
                company_id: 3,
                color: 'cyan',
            }),
        ).toEqual({
            id: 9,
            name: 'api',
            path: '/Users/demo/dev/api',
            root: '/Users/demo/dev/api',
            defaultLaunchProfile: 'codex-yolo',
            companyId: 3,
            color: 'cyan',
        });
    });
});
