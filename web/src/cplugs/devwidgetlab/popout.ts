import manifest from '../../../../src/cplugs/devwidgetlab/cplug.json';
import type { CplugManifest, CplugPopout } from '../sdk';
import { devwidgetlabViewerTab } from './viewer-tab';

export const devwidgetlabPopout: CplugPopout = { id: 'devwidgetlab', manifest: manifest as CplugManifest, tabs: [devwidgetlabViewerTab] };
