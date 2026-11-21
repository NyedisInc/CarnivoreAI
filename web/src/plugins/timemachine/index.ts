import manifest from '../../../../src/plugins/timemachine/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';

export const timemachineCplug: CplugWeb = {
  id: 'timemachine',
  manifest: manifest as CplugManifest,
};
