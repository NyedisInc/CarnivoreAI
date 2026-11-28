import { epochAgo, MIN } from './clock';
import type { WidgetFixtures } from './types';

function item(id: number, status: string, text: string, ageMin: number, last: { author: 'claude' | 'joe'; text: string }, extra: Record<string, unknown> = {}): unknown {
  const question = status === 'question';
  return {
    id, list: '1', text, note: '', position: id, created_by: 'claude', state: status === 'review' ? 'review' : 'open', kind: question ? 'question' : '', number: id,
    revision: 1, created_seq: id, seq: id, deleted: false, status, section: status, needs_you: question || status === 'review', group: null, title: null,
    thread: [{ id: 100 + id, item_id: id, author: last.author, kind: question ? 'question' : 'reply', text: last.text, answered: false, created_at: epochAgo(ageMin * MIN), seq: id }],
    ...extra,
  };
}

const LISTS = { lists: [{ key: '1', name: 'billing-api', project_id: 1, items: 9, open: 9, review: 1, questions: 2, claude_seq: 9, needs_you: 3 }] };

const ITEMS = [
  item(2, 'question', 'should a failed invoice email the customer?', 9, { author: 'claude', text: 'Send the failure email, or hold it for the retry?' }),
  item(3, 'question', 'keep the v1 webhook route for one more release?', 52, { author: 'claude', text: 'Keep it, or cut it now?' }),
  item(4, 'review', 'invoice retries: backoff and the dead letter queue', 300, { author: 'claude', text: 'Backoff is 1, 5 and 25 minutes; the third failure parks it.' }),
  item(5, 'working', 'split the invoice export into pages', 4, { author: 'claude', text: 'Reading the export for the page boundary.' }),
  item(6, 'working', 'rotate the signing key', 33, { author: 'claude', text: 'Writing the rotation script.' }),
  item(7, 'waiting', 'upgrade the queue worker image', 180, { author: 'claude', text: 'Waiting on the image build.' }),
  item(8, 'scheduled', 'daily: check the stuck payouts', 20, { author: 'claude', text: 'Last run found none.' }, { start_trigger: { kind: 'at', fire_at: epochAgo(-180 * MIN), fired_at: null, last_error: null } }),
  item(9, 'open', 'reconcile the March ledger', 2 * 24 * 60, { author: 'joe', text: 'Parked until the audit lands.' }, { created_by: 'joe' }),
  item(10, 'open', 'add a currency column to the export', 6 * 24 * 60, { author: 'claude', text: 'Needs the rounding rule first.' }),
];

export const taskManagerListFixtures: WidgetFixtures = {
  data: {
    'GET /cplugs/huddle/lists': LISTS,
    'GET /cplugs/huddle/aggregate': { cursor: 9, groups: [{ list: '1', name: 'billing-api', project_id: 1, revision: 9, items: ITEMS }] },
  },
  empty: {
    'GET /cplugs/huddle/lists': { lists: [] },
    'GET /cplugs/huddle/aggregate': { cursor: 0, groups: [] },
  },
};
