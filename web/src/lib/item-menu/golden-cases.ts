
export type RowCtx = Record<string, unknown>;

const BASE: RowCtx = {
    name: 'carnivore_alpha',
    label: 'alpha',
    sessionId: 'ses_alpha',
    sessionUuid: 'uuid-alpha',
    conversationId: 'conv-alpha',
    asleep: false,
    archived: false,
    closed: false,
    projectId: 5,
    surface: 'sidebar',
    kind: 'session',
    layoutUuid: '',
    owned: true,
    status: 'working',
    unread: false,
    restartable: true,
    hostKey: 'local',
    agentFamily: 'claude',
    pluginItems: '',
    groupable: true,
    groupUuid: '',
    groupName: '',
    renameable: true,
    renameReason: '',
    isPage: false,
    isFile: false,
    forkable: true,
    forkReason: '',
    muted: false,
    mcpDropped: false,
    mcpServers: '',
    agentUpdateReady: false,
    agentUpdateRunning: '',
    agentUpdateInstalled: '',
    updateBusy: false,
    updateBusyReason: '',
};

const BROWSER: RowCtx = {
    ...BASE,
    name: 'browser:b-1',
    label: 'docs',
    sessionId: null,
    sessionUuid: '',
    conversationId: '',
    kind: 'browser',
    owned: false,
    status: 'unknown',
    restartable: false,
    agentFamily: '',
    forkable: false,
};

export interface RowCase {
    name: string;
    type: 'session' | 'browser' | 'page' | 'file' | 'layout';
    ctx: RowCtx;
}

export const ROW_CASES: readonly RowCase[] = [
    { name: 'session working', type: 'session', ctx: { ...BASE } },
    { name: 'session idle unread', type: 'session', ctx: { ...BASE, status: 'idle', unread: true } },
    { name: 'session finished unread', type: 'session', ctx: { ...BASE, status: 'finished_unread', unread: true } },
    { name: 'session dead', type: 'session', ctx: { ...BASE, status: 'dead' } },
    { name: 'session dead not restartable', type: 'session', ctx: { ...BASE, status: 'dead', restartable: false, owned: false, forkable: false } },
    { name: 'session asleep', type: 'session', ctx: { ...BASE, status: 'idle', asleep: true, restartable: false, sessionId: null } },
    { name: 'session asleep unread', type: 'session', ctx: { ...BASE, status: 'idle', asleep: true, unread: true, restartable: false, sessionId: null } },
    { name: 'session asleep no key', type: 'session', ctx: { ...BASE, status: 'idle', asleep: true, restartable: false, sessionId: null, sessionUuid: '' } },
    { name: 'session closed', type: 'session', ctx: { ...BASE, status: 'dead', closed: true, restartable: false } },
    { name: 'session archived', type: 'session', ctx: { ...BASE, status: 'dead', archived: true, restartable: false } },
    { name: 'session update ready', type: 'session', ctx: { ...BASE, status: 'idle', agentUpdateReady: true, agentUpdateRunning: '2.1.0', agentUpdateInstalled: '2.2.0' } },
    {
        name: 'session update busy', type: 'session',
        ctx: { ...BASE, agentUpdateReady: true, agentUpdateRunning: '2.1.0', agentUpdateInstalled: '2.2.0', updateBusy: true, updateBusyReason: 'cannot update and restart: 1 subagent running - a restart would end it' },
    },
    { name: 'session mcp drop idle', type: 'session', ctx: { ...BASE, status: 'idle', mcpDropped: true, mcpServers: 'github' } },
    { name: 'session mcp drop working', type: 'session', ctx: { ...BASE, mcpDropped: true, mcpServers: 'github, slack' } },
    { name: 'session remote', type: 'session', ctx: { ...BASE, hostKey: 'peer-mini' } },
    { name: 'session adopted', type: 'session', ctx: { ...BASE, owned: false, forkable: false, forkReason: 'cannot fork: carnivore did not create this agent, so it has no recorded conversation to branch from', agentFamily: '' } },
    { name: 'session not renameable', type: 'session', ctx: { ...BASE, renameable: false, renameReason: 'cannot rename: this agent has no live backend to send the change to' } },
    { name: 'session in group', type: 'session', ctx: { ...BASE, groupUuid: 'g-1', groupName: 'crew' } },
    { name: 'session shift held', type: 'session', ctx: { ...BASE, shiftHeld: true } },
    { name: 'session no key', type: 'session', ctx: { ...BASE, sessionUuid: '', conversationId: '' } },
    { name: 'session muted codex', type: 'session', ctx: { ...BASE, muted: true, agentFamily: 'codex' } },
    { name: 'session kept awake', type: 'session', ctx: { ...BASE, name: 'carnivore_kept' } },
    { name: 'session home surface', type: 'session', ctx: { ...BASE, surface: 'home', groupable: false } },
    { name: 'browser', type: 'browser', ctx: { ...BROWSER } },
    { name: 'browser in group', type: 'browser', ctx: { ...BROWSER, groupUuid: 'g-1', groupName: 'crew' } },
    { name: 'page', type: 'page', ctx: { ...BROWSER, name: 'page:p-1', isPage: true } },
    { name: 'file', type: 'file', ctx: { ...BROWSER, name: 'file:f-1', isFile: true } },
    { name: 'layout', type: 'layout', ctx: { ...BROWSER, name: 'layout:l-1', kind: 'layout', layoutUuid: 'l-1' } },
];

export const PLUGIN_CASE_NAMES: readonly string[] = ['session working', 'session idle unread', 'session finished unread', 'session remote'];
