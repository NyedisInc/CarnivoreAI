import { describe, expect, test } from 'vitest';

import { GOOD_FOLDER, GOOD_NAME, enT, modals, recorder } from './create-harness';
import { accountFields, buildCreatePayload, buildOpenProjectPayload, isRemoteRoot, splitRemoteRoot, agentTypeFor, chooseHost, createConsoleFlow, createProjectFlow } from './create-flow';
import type { HostChoice } from './create-host';
import { cloneFromGithubFlow } from './entry-flows';
import { openProjectFromFolderFlow } from './open-folder-flow';

describe('RULE: the folder step cannot be skipped', () => {
    test('a create asks for a folder BEFORE it creates anything', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('created');
        expect(m.asked.map(([kind]) => kind)).toEqual(['name', 'folder']);
        const createdAt = rec.calls.findIndex(([kind]) => kind === 'createSession');
        expect(createdAt).toBeGreaterThan(-1);
        expect(rec.calls.slice(0, createdAt).map(([kind]) => kind)).not.toContain('createProject');
    });

    test('cancelling the folder step creates NOTHING AT ALL', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: null });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('cancelled_folder');
        expect(result.payload).toBe(null);
        expect(rec.calls.map(([kind]) => kind)).not.toContain('createSession');
        expect(rec.calls.map(([kind]) => kind)).not.toContain('createProject');
        expect(rec.errors).toEqual([]);
    });

    test('cancelling the provider gate never even asks for a name', async () => {
        const rec = recorder({ chooseProvider: async () => null });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('cancelled_provider');
        expect(m.asked).toEqual([]);
        expect(rec.calls.map(([kind]) => kind)).not.toContain('createSession');
    });

    test('cancelling the name step never asks for a folder', async () => {
        const rec = recorder();
        const m = modals({ name: [null], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('cancelled_name');
        expect(m.asked.map(([kind]) => kind)).toEqual(['name']);
        expect(rec.calls.map(([kind]) => kind)).not.toContain('createSession');
    });
});

describe('RULE: the field is project_parent_dir, never working_dir', () => {
    test('the create payload carries the chosen PARENT and no working_dir', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);

        const payload = rec.payloads[0]!;
        expect(payload.project_parent_dir).toBe('/Users/me/Development');
        expect('working_dir' in payload).toBe(false);
    });

    test('the chosen folder is posted verbatim, with no name appended', () => {
        const payload = buildCreatePayload('My App', '/Users/me/Development', null, null, {});
        expect(payload.project_parent_dir).toBe('/Users/me/Development');
        expect(Object.values(payload)).not.toContain('/Users/me/Development/My App');
    });

    test('a shell console posts working_dir, and that stays legal', async () => {
        const rec = recorder();
        await createConsoleFlow(rec.host, enT());
        expect(rec.payloads[0]!.working_dir).toBe('~');
        expect('project_parent_dir' in rec.payloads[0]!).toBe(false);
    });
});

describe('RULE: a refused name is re-asked, never rewritten', () => {
    test('an illegal name shows a sentence and re-opens with what was typed', async () => {
        const rec = recorder();
        const m = modals({
            name: [{ name: 'a/b', description: '' }, GOOD_NAME],
            folder: GOOD_FOLDER,
        });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('created');
        const nameAsks = m.asked.filter(([kind]) => kind === 'name');
        expect(nameAsks).toHaveLength(2);
        expect((nameAsks[1]![1] as { defaultName: string }).defaultName).toBe('a/b');
        expect(rec.errors).toEqual(["a project name cannot contain '/'"]);
        expect(rec.payloads[0]!.project_name).toBe('My App');
    });

    test('the refused name is never silently sanitised into the payload', async () => {
        const rec = recorder();
        const m = modals({ name: [{ name: 'a/b', description: '' }], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('cancelled_name');
        expect(rec.payloads).toEqual([]);
        expect(rec.errors).toEqual(["a project name cannot contain '/'"]);
    });
});

describe('what the create posts, beyond the folder', () => {
    test('a claude project sends the name as the session label', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(rec.payloads[0]!.label).toBe('My App');
        expect(rec.payloads[0]!.project_name).toBe('My App');
    });

    test('a shell console sends NO label, because --name is claude-only', async () => {
        const rec = recorder();
        await createConsoleFlow(rec.host, enT());
        expect('label' in rec.payloads[0]!).toBe(false);
        expect(rec.payloads[0]!.agent_type).toBe('shell');
    });

    test('a caller-named working_dir travels, for "new terminal here"', async () => {
        const rec = recorder();
        await createConsoleFlow(rec.host, enT(), '/Users/me/code/api');
        expect(rec.payloads[0]!.working_dir).toBe('/Users/me/code/api');
    });

    test('an empty working_dir still falls back to the home folder', async () => {
        const rec = recorder();
        await createConsoleFlow(rec.host, enT(), '');
        expect(rec.payloads[0]!.working_dir).toBe('~');
    });

    test('the xterm grid rides along so the pane is born the right size', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(rec.payloads[0]!.cols).toBe(132);
        expect(rec.payloads[0]!.rows).toBe(40);
    });

    test('agent_type precedence: an explicit family beats the picker', () => {
        expect(agentTypeFor('openclaw', { wrapperId: 'claude-chrome' })).toBe('openclaw');
        expect(agentTypeFor(null, { wrapperId: 'claude-chrome' })).toBe('claude-chrome');
        expect(agentTypeFor(null, { agentType: 'codex' })).toBe('codex');
        expect(agentTypeFor(null, {})).toBe(null);
        expect('agent_type' in buildCreatePayload('a', '/p', null, {}, {})).toBe(false);
    });

    test('a model is posted only when the picker chose one', () => {
        expect(buildCreatePayload('a', '/p', null, { model: 'm/1' }, {}).model).toBe('m/1');
        expect('model' in buildCreatePayload('a', '/p', null, {}, {})).toBe(false);
    });
});

describe('what happens after the session lands', () => {
    test('the project row is written and the tree is refreshed', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);

        const kinds = rec.calls.map(([kind]) => kind);
        expect(kinds).toContain('createProject');
        expect(kinds).toContain('reloadProjects');
        expect(kinds).toContain('announceSessionCreated');
        const row = rec.calls.find(([kind]) => kind === 'createProject')?.[1] as {
            path: string;
        };
        expect(row.path).toBe('/Users/me/Development/My App');
    });

    test('an existing project row is not a failed create', async () => {
        const rec = recorder({
            createProject: async () => {
                throw new Error('project already exists');
            },
        });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(result.outcome).toBe('created');
        expect(rec.errors).toEqual([]);
    });

    test('a failed repaint is not a failed create either', async () => {
        const rec = recorder({
            reloadProjects: async () => {
                throw new Error('listing unavailable');
            },
        });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(result.outcome).toBe('created');
        expect(rec.errors).toEqual([]);
    });

    test('"already running" detaches and retries rather than refusing', async () => {
        const rec = recorder({
            createSession: async () => {
                throw new Error('a session is already running');
            },
        });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), 'openclaw');
        expect(result.outcome).toBe('detached_and_retried');
        expect(rec.calls).toContainEqual(['detachAndCreateNew', 'openclaw']);
        expect(rec.errors).toEqual([]);
    });

    test('any other failure is reported as a sentence', async () => {
        const rec = recorder({
            createSession: async () => {
                throw new Error('disk is full');
            },
        });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(result.outcome).toBe('failed');
        expect(rec.errors).toEqual(['failed to create session: disk is full']);
    });

    test('an error with no message still says something', async () => {
        const rec = recorder({
            createSession: async () => {
                throw new Error('');
            },
        });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(rec.errors[0]).toBe('failed to create session: the server could not be reached');
    });
});

describe('issue #162 slice S6: which host a create launches on', () => {
    const REMOTE: HostChoice = {
        key: 'studio', label: 'Studio', local: false, ssh_target: 'studio', enabled: true, probe_state: 'ok',
        ssh_port: null, socket: null, session_count: 0, probe_detail: null, probed_at: null,
        tmux_path: null, tmux_version: null, login_path: null, agent_paths: null, login_shell: null,
        machine_id: null, remote_carnivore: null, created_at: '', updated_at: '',
    };

    test('with no remote host configured, nothing is asked and the answer is local', async () => {
        const m = modals({});
        const picked = await chooseHost({ listHosts: async () => [] } as never, m.openers, enT());
        expect(picked?.key).toBe('local');
        expect(m.asked).toEqual([]);
    });

    test('with a remote host configured, the picker is asked and its answer wins', async () => {
        const m = modals({ choice: 'studio' });
        const picked = await chooseHost({ listHosts: async () => [REMOTE] } as never, m.openers, enT());
        expect(picked?.key).toBe('studio');
        expect(m.asked.map(([kind]) => kind)).toEqual(['choice']);
    });

    test('cancelling the host step cancels the whole launch, creating nothing', async () => {
        const rec = recorder({ listHosts: async () => [REMOTE] });
        const m = modals({ choice: null, name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(result.outcome).toBe('cancelled_host');
        expect(rec.calls.map(([kind]) => kind)).not.toContain('createSession');
        expect(m.asked.map(([kind]) => kind)).toEqual(['choice']);
    });

    test('a paired computer posts its folder as project_parent_dir so its own folder checks run (#1952)', async () => {
        const PEER: HostChoice = { ...REMOTE, key: 'peer-studio-test', label: 'studio' };
        const rec = recorder({ listHosts: async () => [PEER] });
        const m = modals({ choice: PEER.key, name: [GOOD_NAME], folder: { parent: '~/carnivore-projects/SoundDesk', path: '~/carnivore-projects/SoundDesk' } });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(result.outcome).toBe('created');
        expect(rec.payloads[0]!.host_key).toBe(PEER.key);
        expect(rec.payloads[0]!.project_parent_dir).toBe('~/carnivore-projects/SoundDesk');
        expect(rec.payloads[0]!.project_name).toBe(GOOD_NAME.name);
        expect('working_dir' in rec.payloads[0]!).toBe(false);
    });

    test('a remote host asks for a far folder and posts it as working_dir, never project_parent_dir', async () => {
        const rec = recorder({ listHosts: async () => [REMOTE] });
        const m = modals({ choice: 'studio', name: [GOOD_NAME], folder: { parent: '~/carnivore-projects/SoundDesk', path: '~/carnivore-projects/SoundDesk' } });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(result.outcome).toBe('created');
        expect(m.asked.map(([kind]) => kind)).toEqual(['choice', 'name', 'folder']);
        expect((m.asked[1]![1] as { confirmLabel: string }).confirmLabel).toBe('next');
        expect(rec.payloads[0]!.host_key).toBe('studio');
        expect(rec.payloads[0]!.working_dir).toBe('~/carnivore-projects/SoundDesk');
        expect('project_parent_dir' in rec.payloads[0]!).toBe(false);
        expect(rec.payloads[0]!.copy_templates).toBe(false);
        expect('model' in rec.payloads[0]!).toBe(false);
    });

    test('the folder step names the host kind: a paired computer makes the folder and has no guessed default, an ssh host needs an existing one', async () => {
        const PEER: HostChoice = { ...REMOTE, key: 'peer-studio-test', label: 'studio' };
        const peer = modals({ choice: PEER.key, name: [GOOD_NAME], folder: { parent: '/x', path: '/x' } });
        await createProjectFlow(recorder({ listHosts: async () => [PEER] }).host, peer.openers, enT(), null);
        const peerAsk = peer.asked[2]![1] as { remote: { creates: boolean }; defaultParent: () => Promise<string | null>; confirmLabel: string };
        expect(peerAsk.remote.creates).toBe(true);
        expect(await peerAsk.defaultParent()).toBe(null);
        expect(peerAsk.confirmLabel).toBe('create project');
        const ssh = modals({ choice: 'studio', name: [GOOD_NAME], folder: { parent: '/x', path: '/x' } });
        await createProjectFlow(recorder({ listHosts: async () => [REMOTE] }).host, ssh.openers, enT(), null);
        const sshAsk = ssh.asked[2]![1] as { remote: { creates: boolean }; defaultParent: () => Promise<string | null> };
        expect(sshAsk.remote.creates).toBe(false);
        expect(await sshAsk.defaultParent()).toBe('~');
        const labels: Array<string | null | undefined> = [];
        const host = recorder({ chooseProvider: async () => null }).host;
        host.chooseProvider = async (_r, go) => { labels.push(go); return null; };
        host.folderPicker = () => async () => '/p/api';
        await cloneFromGithubFlow(host, modals({}).openers, enT());
        await openProjectFromFolderFlow(host, modals({ name: [GOOD_NAME] }).openers, enT());
        expect(labels).toEqual(['next', 'create project']);
    });

    test('a paired computer labelled with its own hostname is listed once, not twice', async () => {
        const m = modals({ choice: 'studio' });
        await chooseHost({ listHosts: async () => [REMOTE, { ...REMOTE, key: 'b', label: 'Box', ssh_target: 'box.lan' }] } as never, m.openers, enT());
        const items = (m.asked[0]![1] as { items: { key: string; sub: string | null }[] }).items;
        expect(items.find((i) => i.key === 'studio')!.sub).toBe(null);
        expect(items.find((i) => i.key === 'b')!.sub).toBe('box.lan');
    });

    test('#1911: the computer is asked BEFORE the launcher, and the launcher list is that computer\'s', async () => {
        const rec = recorder({ listHosts: async () => [REMOTE] });
        const order: string[] = [];
        const hostCalls = rec.host.listHosts;
        rec.host.listHosts = async () => { order.push('hosts'); return hostCalls(); };
        let asked: unknown = 'unset';
        rec.host.chooseProvider = async (remote) => { order.push('launcher'); asked = remote; return { wrapperId: 'cld', farLauncher: true }; };
        const m = modals({ choice: 'studio', name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);
        expect(order).toEqual(['hosts', 'launcher']);
        expect(asked).toEqual({ key: 'studio', label: 'Studio' });
        expect(rec.payloads[0]!.agent_type).toBe('cld');
        expect(rec.payloads[0]!.agent_type_is_far).toBe(true);
    });

    test('#1911: this computer gets no remote target, and a bare family from the old-peer fallback is never flagged', async () => {
        const local = recorder();
        let asked: unknown = 'unset';
        local.host.chooseProvider = async (remote) => { asked = remote; return { wrapperId: 'cld' }; };
        await createProjectFlow(local.host, modals({ name: [GOOD_NAME], folder: GOOD_FOLDER }).openers, enT(), null);
        expect(asked).toBe(null);
        expect('agent_type_is_far' in local.payloads[0]!).toBe(false);

        const old = recorder({ listHosts: async () => [REMOTE] });
        old.host.chooseProvider = async () => ({ wrapperId: 'claude', farLauncher: false });
        await createProjectFlow(old.host, modals({ choice: 'studio', name: [GOOD_NAME], folder: GOOD_FOLDER }).openers, enT(), null);
        expect(old.payloads[0]!.agent_type).toBe('claude');
        expect('agent_type_is_far' in old.payloads[0]!).toBe(false);
    });

    test('a local launch is unchanged: host_key is never sent', async () => {
        const rec = recorder();
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        await createProjectFlow(rec.host, m.openers, enT(), null);
        expect('host_key' in rec.payloads[0]!).toBe(false);
        expect(rec.payloads[0]!.project_parent_dir).toBe(GOOD_FOLDER.parent);
    });
});

describe('the account fields of a create body (#1641)', () => {
    test('a local launch sends the chosen account and the always-box; a remote project never does', () => {
        const choice = { accountId: 'play', pinAccount: true } as never;
        expect(accountFields(choice, true)).toEqual({ account_id: 'play', account_pinned: true });
        expect(accountFields({ accountId: 'play' } as never, true)).toEqual({ account_id: 'play' });
        expect(accountFields(choice, false)).toEqual({});
        expect(accountFields(null, true)).toEqual({});
    });
});

describe('RULE: a refused project root is shown, not swallowed (P23)', () => {
    test('a 409 project_root_refused reaches the error line in the catalog words', async () => {
        const refusal = Object.assign(new Error('refused'), { status: 409, body: { code: 'project_root_refused' } });
        const rec = recorder({ createProject: async () => { throw refusal; } });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('created');
        const shown = rec.calls.filter(([kind]) => kind === 'showError').map(([, message]) => String(message));
        expect(shown).toHaveLength(1);
        expect(shown[0]).toContain('base folder');
    });
});

describe('RULE: a shell console never toasts a refused project root', () => {
    test('a new console in a folder that holds other projects opens with no error line', async () => {
        const refusal = Object.assign(new Error('refused'), { status: 409, body: { code: 'project_root_refused' } });
        const rec = recorder({ createProject: async () => { throw refusal; } });
        const result = await createConsoleFlow(rec.host, enT());

        expect(result.outcome).toBe('created');
        expect(rec.calls.filter(([kind]) => kind === 'showError')).toHaveLength(0);
    });
});

describe('RULE: a refused folder creates no session (#1928)', () => {
    test('a 409 project_root_refused from the folder check stops the flow before createSession', async () => {
        const refusal = Object.assign(new Error('refused'), { status: 409, body: { code: 'project_root_refused' } });
        const rec = recorder({ checkProjectRoot: async () => { throw refusal; } });
        const m = modals({ name: [GOOD_NAME], folder: GOOD_FOLDER });
        const result = await createProjectFlow(rec.host, m.openers, enT(), null);

        expect(result.outcome).toBe('failed');
        expect(rec.calls.some(([kind]) => kind === 'createSession')).toBe(false);
        expect(rec.calls.some(([kind]) => kind === 'createProject')).toBe(false);
        const shown = rec.calls.filter(([kind]) => kind === 'showError').map(([, message]) => String(message));
        expect(shown).toHaveLength(1);
        expect(shown[0]).toContain('base folder');
    });
});

describe('opening an existing project builds its body by the same local-only rules (u141-05)', () => {
    const choice = { model: 'opus', accountId: 'play', pinAccount: true, wrapperId: 'claude-chrome' };

    test('a local root sends the model, the account pin and the agent', () => {
        expect(buildOpenProjectPayload('api', '/Users/me/api', choice as never, { cols: 80 })).toEqual({
            working_dir: '/Users/me/api', auto_start_claude: true, copy_templates: false, project_name: 'api', label: 'api',
            cols: 80, agent_type: 'claude-chrome', model: 'opus', account_id: 'play', account_pinned: true,
        });
    });

    test('an ssh:// or peer:// root carries its computer and far folder, like create does', () => {
        expect(buildOpenProjectPayload('api', 'ssh://studio/home/api', choice as never, {})).toMatchObject({ host_key: 'studio', working_dir: '/home/api' });
        expect(buildOpenProjectPayload('api', 'peer://peer-ab12/Users/me/api', choice as never, {})).toMatchObject({ host_key: 'peer-ab12', working_dir: '/Users/me/api' });
        expect(buildOpenProjectPayload('api', '/Users/me/api', null, {})).not.toHaveProperty('host_key');
    });

    test('splitRemoteRoot refuses a local path and a root with no far folder', () => {
        expect(splitRemoteRoot('/Users/me/api')).toBeNull();
        expect(splitRemoteRoot('ssh://studio')).toBeNull();
        expect(splitRemoteRoot('ssh:///x')).toBeNull();
    });

    test('an ssh:// or peer:// root sends neither the model nor the account', () => {
        for (const root of ['ssh://studio/home/api', 'peer://mini/Users/me/api']) {
            const body = buildOpenProjectPayload('api', root, choice as never, {});
            expect(body).not.toHaveProperty('model');
            expect(body).not.toHaveProperty('account_id');
            expect(isRemoteRoot(root)).toBe(true);
        }
        expect(isRemoteRoot('/Users/me/api')).toBe(false);
    });
});
