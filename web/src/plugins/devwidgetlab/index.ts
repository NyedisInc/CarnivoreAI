import manifest from '../../../../src/plugins/devwidgetlab/carnivore.toml';
import type { CplugManifest, CplugWeb } from '../sdk';
import { devwidgetlabTab } from './lab-tab';

export const devwidgetlabCplug: CplugWeb = { id: 'devwidgetlab', manifest: manifest as CplugManifest, tabs: [devwidgetlabTab] };
