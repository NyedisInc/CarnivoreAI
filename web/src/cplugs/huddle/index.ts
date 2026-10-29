import manifest from '../../../../src/cplugs/huddle/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';
import { publishActiveProject, registerMarkdown, registerSwarmAgentActions, registerSwarmFace, registerSwarmRoster, unregisterSwarmAgentActions, unregisterSwarmFace, unregisterSwarmRoster } from '../sdk';
import SwarmMemberFace from './swarm/SwarmMemberFace.svelte';
import { registerSwarmFlyout } from './swarm-flyout';
import { taskManagerTab } from './task-manager-tab';
import { startTaskManager } from './huddle.svelte';
import { openAgentTerminal } from './agents/agent-terminal';
import { renameAgent, turnOffAgent, wakeAgent } from './chat/chat-api';
import { refreshRoster, startSwarmRoster, swarmRoster } from './agents/agent-roster.svelte';
import { startFocus } from './task-manager-focus.svelte';
import { startViewCommands } from './task-manager-view-commands';
import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
import { mdPlain } from './task-manager-markdown';
import { startProgress } from './task-manager-progress.svelte';
import { startSwarmSwitch } from '../../lib/swarm-switch/control.svelte';
import { startSendQueue } from './task-manager-send-queue.svelte';
import { chatWidget } from './chat';
import { roleActions } from './session-roles-action';
import { startSessionNudge } from './task-manager-session-prefs';
import './swarm/characters/characters.css';

export const huddleCplug: CplugWeb = {
  id: 'huddle',
  manifest: manifest as CplugManifest,
  tabs: [taskManagerTab],
  widgets: [chatWidget],
  plugins: roleActions,
  stop: () => {
    unregisterSwarmFace();
    unregisterSwarmRoster();
    unregisterSwarmAgentActions();
  },
  start: () => {
    startSwarmSwitch();
    registerSwarmFlyout();
    registerSwarmFace(SwarmMemberFace);
    startTaskManager();
    registerSwarmRoster({ agents: () => swarmRoster.agents, refresh: refreshRoster });
    registerSwarmAgentActions({ wake: wakeAgent, rename: renameAgent, turnOff: turnOffAgent, openTerminal: openAgentTerminal });
    startSwarmRoster();
    startFocus();
    registerMarkdown({ Block: TaskManagerMarkdown, plain: mdPlain });
    startViewCommands();
    startSessionNudge();
    startSendQueue();
    startProgress();
    publishActiveProject();
  },
};
