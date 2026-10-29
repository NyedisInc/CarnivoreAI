import manifest from '../../../../src/cplugs/tmdevtools/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';
import { startCommands } from './commands';

export const tmdevtoolsCplug: CplugWeb = { id: 'tmdevtools', manifest: manifest as CplugManifest, start: startCommands };
