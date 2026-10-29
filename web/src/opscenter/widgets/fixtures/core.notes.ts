import { ago, MIN } from './clock';
import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const NOTE_ROUTE = 'GET /sessions/cloude_billing-api/note';

export const notesFixtures: WidgetFixtures = {
  data: {
    [NOTE_ROUTE]: {
      status: 'ok',
      revision: 7,
      body: '# retry policy\n\n- webhooks retry 5 times with backoff\n- failed invoices go to the review queue\n\n**next:** confirm the plan-change migration with finance',
      updated_at: ago(12 * MIN),
    },
    'GET /sessions/list': sessionList(),
  },
  empty: {
    [NOTE_ROUTE]: { status: 'ok', revision: 0, body: '', updated_at: null },
    'GET /sessions/list': sessionList(),
  },
};
