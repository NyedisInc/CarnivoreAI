import { epochAgo, MIN } from './clock';
import { approvalsFixtures } from './approval-items';
import type { WidgetFixtures } from './types';

function waiting(id: number, text: string, ageMin: number): unknown {
  return {
    id, list: '1', text, note: '', position: id, created_by: 'claude', state: 'open', kind: 'question', number: id, revision: 1,
    created_seq: id, seq: id, deleted: false, status: 'question', section: 'question', needs_you: true, group: null, title: null,
    thread: [{ id: 100 + id, item_id: id, author: 'claude', kind: 'question', text, answered: false, created_at: epochAgo(ageMin * MIN), seq: id }],
  };
}

const LISTS = { lists: [{ key: '1', name: 'billing-api', project_id: 1, items: 2, open: 2, review: 0, questions: 2, claude_seq: 2, needs_you: 2 }] };

export const questionsFixtures: WidgetFixtures = {
  data: {
    ...approvalsFixtures.data,
    'GET /cplugs/huddle/lists': LISTS,
    'GET /cplugs/huddle/aggregate': {
      cursor: 2,
      groups: [{ list: '1', name: 'billing-api', project_id: 1, revision: 2, items: [waiting(2, 'should a failed invoice email the customer?', 9), waiting(3, 'keep the v1 webhook route for one more release?', 52)] }],
    },
  },
  empty: {
    ...approvalsFixtures.empty,
    'GET /cplugs/huddle/lists': { lists: [] },
    'GET /cplugs/huddle/aggregate': { cursor: 0, groups: [] },
  },
};
