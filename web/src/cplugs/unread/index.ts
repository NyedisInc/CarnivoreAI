/* could not */
import manifest from '../../../../src/cplugs/unread/cplug.json';
import { t } from '../sdk';
import type { CplugManifest, CplugWeb, Contribution } from '../sdk';

export const FLAG = 'show_mark_unread_control';

export const ACTION_ID = 'mark-unread';

interface UnreadApi {
  setSessionUnread(tmuxName: string, unread: boolean): Promise<unknown>;
}

function unreadApi(): UnreadApi | null {
  const api = (globalThis as { API?: UnreadApi }).API;
  return api && typeof api.setSessionUnread === 'function' ? api : null;
}

const contribution: Contribution<'session-card-action'> = {
  id: ACTION_ID,
  surface: 'session-card-action',
  order: 200,
  enabled: (context) => context.flags[FLAG] !== false,
  payload: {
    shortcut: 'U',
    label: (row) => t(row.unread ? 'cplug.unread.clear' : 'cplug.unread.set'),
    async run(row, context): Promise<void> {
      const api = unreadApi();
      if (!api) {
        console.error('[unread] window.API is not available');
        return;
      }
      try {
        await api.setSessionUnread(row.name, !row.unread);
      } catch (err) {
        console.error('[unread] failed:', err);
        return;
      }
      await context.refresh();
    },
  },
};

export const unreadCplug: CplugWeb = {
  id: 'unread',
  manifest: manifest as CplugManifest,
  plugins: [contribution],
};
