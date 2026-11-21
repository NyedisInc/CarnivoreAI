import manifest from '../../../../src/plugins/sessionchat/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';

export const sessionchatCplug: CplugWeb = {
  id: 'sessionchat',
  manifest: manifest as CplugManifest,
};
