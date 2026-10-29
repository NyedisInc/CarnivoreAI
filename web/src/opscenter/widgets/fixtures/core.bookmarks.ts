import { ago, HOUR, MIN } from './clock';
import { sessionList, TERMINAL_ROW_ID } from './made-up';
import type { WidgetFixtures } from './types';

const SESSION_ROUTE = `GET /sessions/${TERMINAL_ROW_ID}/bookmarks`;
const CONVERSATION = '4a7c1e90-52d3-4f08-9b61-0c3d8e2a7f11';

function mark(id: number, rowId: number, uuid: string, label: string, by: 'owner' | 'claude', agoS: number, snippet: string): unknown {
  return {
    id, session_uuid: uuid, session_row_id: rowId, claude_session_uuid: CONVERSATION, entry_uuid: `entry-${id}`, label,
    created_by: by, created_at: ago(agoS), snippet, entry_timestamp: ago(agoS + MIN),
  };
}

const BILLING_UUID = '8f1c2d3e-4a5b-4c6d-8e7f-9a0b1c2d3e4f';
const DOCS_UUID = '2b3c4d5e-6f70-4812-93a4-b5c6d7e8f901';

const BILLING_MARKS = [
  mark(1, TERMINAL_ROW_ID, BILLING_UUID, 'before the backoff change', 'owner', 40 * MIN, 'lets add exponential backoff to the retry'),
  mark(2, TERMINAL_ROW_ID, BILLING_UUID, 'the plan-change migration works end to end with the staging mirror and the dead letter queue', 'claude', 3 * HOUR, 'migration applied cleanly'),
];

const SESSION_LIST = { session_uuid: BILLING_UUID, conversation: CONVERSATION, family: 'claude', bookmarks: BILLING_MARKS };
const EMPTY_LIST = { session_uuid: BILLING_UUID, conversation: CONVERSATION, family: 'claude', bookmarks: [] };

function across(one: unknown, label: string, tmux: string): unknown {
  return { ...(one as object), session_label: label, session_tmux: tmux, family: 'claude' };
}

export const bookmarksFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    [SESSION_ROUTE]: SESSION_LIST,
    'GET /bookmarks': {
      bookmarks: [
        across(BILLING_MARKS[0], 'billing-api', 'cloude_billing-api'),
        across(mark(3, 9002, DOCS_UUID, 'search index rebuilt', 'owner', 90 * MIN, 'regenerate the search index'), 'docs-site', 'cloude_docs-site'),
        across(BILLING_MARKS[1], 'billing-api', 'cloude_billing-api'),
      ],
    },
  },
  empty: {
    'GET /sessions/list': sessionList(),
    [SESSION_ROUTE]: EMPTY_LIST,
    'GET /bookmarks': { bookmarks: [] },
  },
};
