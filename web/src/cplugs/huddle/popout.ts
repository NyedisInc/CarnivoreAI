import manifest from '../../../../src/cplugs/huddle/cplug.json';
import type { CplugManifest, CplugPopout } from '../sdk';
import { taskManagerTab } from './task-manager-tab';
import { chatWidget } from './chat';

export const taskManagerPopout: CplugPopout = { id: 'huddle', manifest: manifest as CplugManifest, tabs: [taskManagerTab], widgets: [chatWidget] };
