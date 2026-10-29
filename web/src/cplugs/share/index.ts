import manifest from '../../../../src/cplugs/share/cplug.json';
import { openModal, requireAccount, t } from '../sdk';
import type { CplugManifest, CplugWeb, Contribution } from '../sdk';
import ShareModal from './ShareModal.svelte';

export const ACTION_ID = 'share-read-only';

const contribution: Contribution<'session-card-action'> = {
  id: ACTION_ID,
  surface: 'session-card-action',
  order: 260,
  feature: 'share_link',
  enabled: () => true,
  payload: {
    shortcut: 'S',
    label: () => t('cplug.share.item'),
    async run(row): Promise<void> {
      const sessionId = row.sessionId;
      if (!sessionId) {
        console.error('[share] row carries no session id');
        return;
      }
      const open = async (): Promise<void> => {
        await openModal<null, Record<string, unknown>>(ShareModal as never, { sessionId });
      };
      await requireAccount({ feature: 'share_link', src: 'share_link', resume: () => void open() });
    },
  },
};

export const shareCplug: CplugWeb = {
  id: 'share',
  manifest: manifest as CplugManifest,
  plugins: [contribution],
};
