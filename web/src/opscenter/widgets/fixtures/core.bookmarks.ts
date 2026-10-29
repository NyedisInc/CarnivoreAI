import { ago, HOUR, MIN } from './clock';
import { sessionList, TERMINAL_ROW_ID } from './made-up';
import type { WidgetFixtures } from './types';

const SESSION_ROUTE = `GET /sessions/${TERMINAL_ROW_ID}/bookmarks`;
const CONVERSATION = 'c51d7ccc-df2b-4ba0-898a-0a7a1b906585';

function mark(id: number, rowId: number, uuid: string, label: string, by: 'owner' | 'claude', agoS: number, snippet: string): unknown {
  return {
    id, session_uuid: uuid, session_row_id: rowId, claude_session_uuid: CONVERSATION, entry_uuid: `entry-${id}`, label,
    created_by: by, created_at: ago(agoS), snippet, entry_timestamp: ago(agoS + MIN),
  };
}

const BILLING_UUID = '0edffbc5-38a8-4edc-8c9a-e9bab14a8b5d';
const DOCS_UUID = '295ed3d7-3bc0-4501-8a4c-bd028eedf045';

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
