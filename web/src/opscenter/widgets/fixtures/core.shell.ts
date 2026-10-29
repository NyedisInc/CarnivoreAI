import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const SHELL_ROUTE = 'POST /sessions/ses_billingapi/shell';

function shellBody(state: 'created' | 'existing'): unknown {
  return {
    agent_session_id: 'ses_billingapi',
    agent_row_id: 9001,
    session_id: 'ses_billingapishell',
    session_row_id: 9101,
    tmux_session: 'cloude_billing-api-shell',
    working_dir: '/work/billing-api',
    state,
    pane: 'live',
    session: { session: { id: 'ses_billingapishell', working_dir: '/work/billing-api' }, tmux_session: 'cloude_billing-api-shell', session_row_id: 9101 },
  };
}

export const shellFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    [SHELL_ROUTE]: shellBody('existing'),
    'GET /sessions/ses_billingapi/shell': shellBody('existing'),
  },
  empty: {
    'GET /sessions/list': sessionList(),
    [SHELL_ROUTE]: shellBody('created'),
    'GET /sessions/ses_billingapi/shell': shellBody('created'),
  },
};
