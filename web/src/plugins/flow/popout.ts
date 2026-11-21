import manifest from '../../../../src/plugins/flow/cplug.json';
import type { CplugManifest, CplugPopout } from '../sdk';
import { flowTab } from './flow-tab';

export const flowPopout: CplugPopout = { id: 'flow', manifest: manifest as CplugManifest, tabs: [flowTab] };
