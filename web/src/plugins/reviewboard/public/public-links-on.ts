import manifest from '../../../../../src/plugins/reviewboard/cplug.json';
import type { CplugManifest } from '../../sdk';
import { cplugEnabled, cplugSetting } from '../../sdk';

export const PUBLIC_LINKS_KEY = 'publicLinksEnabled';

const MANIFEST = manifest as CplugManifest;

export function publicLinksOn(): boolean {
  return cplugEnabled(MANIFEST) && cplugSetting<unknown>(MANIFEST, PUBLIC_LINKS_KEY, false) === true;
}
