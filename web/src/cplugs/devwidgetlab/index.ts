import manifest from '../../../../src/cplugs/devwidgetlab/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';
import { devwidgetlabTab } from './lab-tab';

export const devwidgetlabCplug: CplugWeb = { id: 'devwidgetlab', manifest: manifest as CplugManifest, tabs: [devwidgetlabTab] };
