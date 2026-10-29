import { ago, MIN } from './clock';
import type { WidgetFixtures } from './types';

function toast(n: number, kind: string, title: string, body: string | null, label: string, name: string, agoSeconds: number): unknown {
  return {
    id: `toast-${n}`,
    session_id: `ses_${name.replace('cloude_', '').replace(/-/g, '')}`,
    kind,
    title,
    body,
    session_label: label,
    session_name: name,
    created_at: ago(agoSeconds),
    acknowledged: n > 4,
  };
}

const STORAGE = 'held in the server process; cleared when it restarts';

export const activityLogFixtures: WidgetFixtures = {
  data: {
    'GET /toasts/history': {
      total: 8,
      storage: STORAGE,
      toasts: [
        toast(1, 'PermissionRequest', 'wants to run a command', 'npm run build', 'docs-site', 'cloude_docs-site', 4 * MIN),
        toast(2, 'Stop', 'finished', 'migration for plan changes is ready to review', 'billing-api', 'cloude_billing-api', 9 * MIN),
        toast(3, 'Notification', 'needs your input', 'which retry policy should webhooks use?', 'billing webhooks', 'cloude_billing-webhooks', 17 * MIN),
        toast(4, 'Stop', 'finished', 'push token refresh is done', 'mobile-app', 'cloude_mobile-app', 26 * MIN),
        toast(5, 'PermissionRequest', 'wants to edit a file', 'deploy/monitor.yaml', 'infra-tools', 'cloude_infra-tools', 41 * MIN),
        toast(6, 'Stop', 'finished', 'search index rebuilt', 'docs-site', 'cloude_docs-site', 58 * MIN),
        toast(7, 'Notification', 'needs your input', 'keep the old invoice format?', 'billing-api', 'cloude_billing-api', 83 * MIN),
        toast(8, 'Stop', 'finished', 'monitor alerts verified', 'infra-tools', 'cloude_infra-tools', 120 * MIN),
      ],
    },
  },
  empty: {
    'GET /toasts/history': { total: 0, storage: STORAGE, toasts: [] },
  },
};
