import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const SESSION_ROUTE = 'GET /sessions/ses_billingapi/tasks';

function task(id: string, subject: string, status: 'pending' | 'in_progress' | 'completed', activeForm: string | null = null): unknown {
  return { id, subject, active_form: activeForm, status };
}

function list(sessionId: string, label: string, tasks: Array<ReturnType<typeof task>>): unknown {
  const status = (one: unknown): string => (one as { status: string }).status;
  const count = (wanted: string): number => tasks.filter((one) => status(one) === wanted).length;
  return {
    state: 'ok',
    session_id: sessionId,
    label,
    tasks,
    counts: { pending: count('pending'), in_progress: count('in_progress'), completed: count('completed') },
  };
}

const BILLING = list('ses_billingapi', 'billing-api', [
  task('1', 'read the retry policy and the webhook handler', 'completed'),
  task('2', 'add exponential backoff to the failed invoice retry', 'in_progress', 'adding exponential backoff to the failed invoice retry'),
  task('3', 'write the dead letter queue migration', 'pending'),
  task('4', 'cover the third failure parking path with a test', 'pending'),
  task('5', 'update the retry policy docs, then re-verify every webhook endpoint against the staging mirror and write down what changed', 'pending'),
]);

const DOCS = list('ses_docssite', 'docs-site', [
  task('1', 'audit the sidebar for dead links', 'completed'),
  task('2', 'move the changelog under releases', 'completed'),
  task('3', 'regenerate the search index', 'in_progress', 'regenerating the search index'),
]);

const NONE = { state: 'empty', session_id: 'ses_billingapi', label: 'billing-api', tasks: [], counts: { pending: 0, in_progress: 0, completed: 0 } };

export const tasksFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    [SESSION_ROUTE]: BILLING,
    'GET /session-tasks': { sessions: [BILLING, DOCS] },
  },
  empty: {
    'GET /sessions/list': sessionList(),
    [SESSION_ROUTE]: NONE,
    'GET /session-tasks': { sessions: [] },
  },
};
