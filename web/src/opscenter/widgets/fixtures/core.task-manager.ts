import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const LIST = '1';

interface ItemExtras {
  status?: string;
  section?: string;
  group?: number;
  title?: string;
  marker?: string;
  thread?: unknown[];
  needsYou?: boolean;
}

function item(id: number, text: string, state: string, kind: string, by: 'joe' | 'claude', extras: ItemExtras = {}): unknown {
  const status = extras.status ?? (state === 'review' ? 'review' : 'open');
  return {
    id, list: LIST, text, note: '', position: id, created_by: by, state, kind, number: id, revision: 1, created_seq: id, seq: id, deleted: false,
    status, section: extras.section ?? status, needs_you: extras.needsYou ?? false, group: extras.group ?? null,
    title: extras.title ?? null, marker: extras.marker ?? null, thread: extras.thread ?? [],
  };
}

function group(id: number, name: string): unknown {
  return { id, list: LIST, name, position: id, folded: false };
}

function questionPost(itemId: number, text: string): unknown {
  return { id: 100 + itemId, item_id: itemId, author: 'claude', kind: 'question', text, answered: false, created_at: 1_760_000_000, seq: itemId };
}

const ITEMS: unknown[] = [
  item(1, 'retry failed webhooks with backoff', 'open', '', 'joe', { group: 1, title: 'retry **failed** webhooks with `backoff`' }),
  item(2, 'should a failed invoice email the customer?', 'open', 'question', 'claude', {
    status: 'question', needsYou: true, thread: [questionPost(2, 'should a failed invoice email the customer, or only the account owner?')],
  }),
  item(3, 'review queue for failed invoices', 'review', 'done', 'claude', { group: 2, title: 'review queue for *failed* invoices' }),
  item(4, 'rotate the signing key before the plan migration, then re-verify every webhook endpoint against the staging mirror and write down what changed',
    'open', '', 'joe', { group: 2 }),
  item(5, 'audit the retry policy docs', 'open', '', 'claude', { marker: 'cross' }),
  item(6, 'migrate legacy stripe v1 calls', 'todo', '', 'joe', { status: 'todo', section: 'todo', title: 'migrate [legacy](https://example.com) stripe v1 calls' }),
];

function lists(count: number): unknown {
  return { lists: [{ key: LIST, name: 'billing-api', project_id: 1, items: count, open: count, review: 0, questions: 0, claude_seq: 0 }] };
}

export const taskManagerFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    'GET /cplugs/huddle/lists': lists(ITEMS.length),
    [`GET /cplugs/huddle/lists/${LIST}`]: { list: LIST, revision: 6, cursor: 6, groups: [group(1, 'webhooks'), group(2, 'invoices')], items: ITEMS },
  },
  empty: {
    'GET /sessions/list': sessionList(),
    'GET /cplugs/huddle/lists': lists(0),
    [`GET /cplugs/huddle/lists/${LIST}`]: { list: LIST, revision: 0, cursor: 0, groups: [], items: [] },
  },
};
