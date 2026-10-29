/* the plugins page */
import manifest from '../../../../src/cplugs/publicboard/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';

export const publicboardCplug: CplugWeb = { id: 'publicboard', manifest: manifest as CplugManifest };
