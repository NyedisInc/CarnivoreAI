import manifest from '../../../../src/plugins/devwidgetlab/carnivore.toml';
import type { CplugManifest, CplugPopout } from '../sdk';
import { devwidgetlabViewerTab } from './viewer-tab';

export const devwidgetlabPopout: CplugPopout = { id: 'devwidgetlab', manifest: manifest as CplugManifest, tabs: [devwidgetlabViewerTab] };
