/* the plugins page */
import manifest from '../../../../src/cplugs/publicboard/cplug.json';
import type { CplugManifest, CplugWeb } from '../sdk';
import { cplugEnabled, registerBoardHeaderKey, registerPageRowAction } from '../sdk';
import { sharePageRowAction } from './page-row-action';
import ShareLinkKey from './ShareLinkKey.svelte';

export const publicboardCplug: CplugWeb = {
  id: 'publicboard', manifest: manifest as CplugManifest, start: () => {
    registerBoardHeaderKey({ id: 'publicboard.share', component: ShareLinkKey, enabled: () => cplugEnabled(publicboardCplug.manifest) });
    registerPageRowAction(sharePageRowAction(() => cplugEnabled(publicboardCplug.manifest)));
  },
};
