import manifest from '../../../../src/plugins/taskmanager/carnivore.toml';
import type { CplugManifest, CplugPopout } from '../sdk';
import { taskManagerTab } from './task-manager-tab';
import { chatWidget } from './chat';
import { taskManagerCells } from './cells';

export const taskManagerPopout: CplugPopout = { id: 'taskmanager', manifest: manifest as CplugManifest, tabs: [taskManagerTab], widgets: [chatWidget], cells: taskManagerCells };
