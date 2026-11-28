import manifest from '../../../../src/plugins/sessionchat/carnivore.toml';
import type { CplugManifest, CplugWeb } from '../sdk';

export const sessionchatCplug: CplugWeb = {
  id: 'sessionchat',
  manifest: manifest as CplugManifest,
};
