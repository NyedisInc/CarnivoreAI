import { register } from './registry';
import type { Plugin } from './types';
import { cplugPlugins } from '../../plugins/host/readers';

export const BUILTIN: readonly Plugin[] = cplugPlugins();

for (const plugin of BUILTIN) register(plugin);
