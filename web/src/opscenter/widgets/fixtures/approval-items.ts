import { epochAgo, MIN } from './clock';
import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const FINGERPRINT = 'a'.repeat(64);

export const approvalsFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    'GET /approvals': {
      items: [
        {
          id: 'dialog-1',
          source: 'dialog',
          host: 'local',
          session_id: 'ses_docssite',
          session_name: 'docs-site',
          project: 'docs-site',
          family: 'claude',
          kind: 'permission',
          question: 'Do you want to run this command?',
          rows: [
            { label: 'Yes', role: 'option' },
            { label: 'Yes, and do not ask again for npm run', role: 'option' },
            { label: 'No, and tell Claude what to do differently', role: 'other' },
          ],
          multi_select: false,
          has_other: true,
          fingerprint: FINGERPRINT,
          question_index: null,
          question_total: null,
          tabs: [],
          body: 'npm run build -- --mode production',
          created_at: epochAgo(4 * MIN),
        },
        {
          id: 'dialog-2',
          source: 'dialog',
          host: 'local',
          session_id: 'ses_billingwebhooks',
          session_name: 'billing webhooks',
          project: 'billing-api',
          family: 'claude',
          kind: 'question',
          question: 'Which retry policy should failed webhooks use?',
          rows: [
            { label: 'Exponential backoff', role: 'option', description: 'retry 5 times over about an hour' },
            { label: 'Fixed interval', role: 'option', description: 'retry every 10 minutes for a day' },
            { label: 'Type something', role: 'other' },
          ],
          multi_select: false,
          has_other: true,
          fingerprint: FINGERPRINT,
          question_index: null,
          question_total: null,
          tabs: [],
          body: '',
          created_at: epochAgo(17 * MIN),
        },
        {
          id: 'action-1',
          source: 'agent_action',
          host: 'local',
          session_id: 'ses_infratools',
          session_name: 'infra-tools',
          project: 'infra-tools',
          kind: 'session_stop',
          action: 'stop the session',
          summary: 'stop the infra-tools session',
          caller: 'cloude_billing-webhooks',
          tmux_session: 'cloude_infra-tools',
          created_at: epochAgo(31 * MIN),
        },
      ],
    },
  },
  empty: {
    'GET /approvals': { items: [] },
  },
};
