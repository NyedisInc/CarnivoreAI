import { epochAgo, DAY, HOUR, MIN } from './clock';
import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

interface Side {
  key: string; id: string; session_uuid: null; name: string; provider: string; model: string;
  project_id: number | null; project_name: string | null;
}

function side(id: string, name: string, provider: string, model: string, project: number | null, projectName: string | null): Side {
  return { key: id, id, session_uuid: null, name, provider, model, project_id: project, project_name: projectName };
}

const BILLING = side('ses_billingapi', 'billing-api', 'claude', 'opus 5.5', 1, 'billing-api');
const DOCS = side('ses_docssite', 'docs-site', 'claude', 'sonnet 5.5', 2, 'docs-site');
const MOBILE = side('ses_mobileapp', 'mobile-app', 'claude', 'sonnet 5.5', 3, 'mobile-app');
const INFRA = side('ses_infratools', 'infra-tools', 'codex', 'gpt 5.2', 4, 'infra-tools');
const HOOKS = side('ses_billingwebhooks', 'billing webhooks', 'claude', 'opus 5.5', 1, 'billing-api');
const RECON = side('ses_recon', 'payments reconciliation nightly worker', 'claude', 'haiku 5', 1, 'billing-api');

function msg(id: string, thread: string, from: Side, to: Side, text: string, agoS: number, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id, source: 'crosstalk', thread, sender_key: from.key, receiver_key: to.key, sender_id: from.id, sender_uuid: null,
    sender_name: from.name, sender_provider: from.provider, sender_model: from.model, receiver_id: to.id, receiver_uuid: null,
    receiver_name: to.name, receiver_provider: to.provider, receiver_model: to.model, text, status: 'delivered', reason: null,
    in_reply_to: null, expect_reply: 0, created_at: epochAgo(agoS), ...extra,
  };
}

function notice(id: string, thread: string, to: Side, text: string, agoS: number): Record<string, unknown> {
  return { ...msg(id, thread, to, to, text, agoS), source: 'system', sender_key: 'system', sender_id: 'system', sender_name: 'carnivore' };
}

const LONG_DRAFT = [
  'here is the draft of the retry policy page:',
  '',
  'retries',
  'the api client retries a failed call three times.',
  'it waits 2 seconds, then 8 seconds, then 30 seconds.',
  'when the server answers with a Retry-After header, that wait wins.',
  'webhooks keep their own schedule; see the webhooks page.',
  '',
  'what is retried',
  'timeouts, connection resets, and answers 429, 502, 503 and 504.',
  'nothing else is retried: a 400 or a 409 means the request itself is wrong.',
  '',
  'i kept the old example and changed its numbers to match.',
].join('\n');

const MESSAGES: Record<string, Record<string, unknown>[]> = {
  't-retry': [
    msg('r1', 't-retry', BILLING, DOCS, 'the retry policy changed: 3 attempts, backoff 2s, 8s, 30s. please update the retry policy page in the docs.', 26 * HOUR, { expect_reply: 1 }),
    msg('r2', 't-retry', DOCS, BILLING, 'on it. does the 30s step apply to webhooks too, or only to the api client?', 26 * HOUR - 10 * MIN, { in_reply_to: 'r1', expect_reply: 1 }),
    msg('r3', 't-retry', BILLING, DOCS, 'api client only. webhooks keep their own schedule.', 26 * HOUR - 20 * MIN, { in_reply_to: 'r2' }),
    msg('r4', 't-retry', BILLING, DOCS, 'also say that a Retry-After header from the server wins over our backoff.', 26 * HOUR - 22 * MIN),
    msg('r5', 't-retry', DOCS, BILLING, LONG_DRAFT, 12 * MIN),
    msg('r6', 't-retry', DOCS, BILLING, 'the retry policy page is updated, can you check the numbers before i publish?', 8 * MIN, { in_reply_to: 'r3', expect_reply: 1 }),
  ],
  't-webhooks': [
    msg('w1', 't-webhooks', HOOKS, BILLING, 'webhook signatures verified against the staging mirror, every endpoint answers 200 and the dead letter queue stays empty.', 3 * HOUR),
    notice('w-n', 't-webhooks', BILLING, 'billing webhooks went idle.', 2 * HOUR),
    msg('w2', 't-webhooks', BILLING, HOOKS, 'please rerun the signature check against staging once your current task finishes.', 40 * MIN, { status: 'held', reason: 'billing webhooks is busy; delivered when it is ready', expect_reply: 1 }),
  ],
  't-schema': [
    msg('s1', 't-schema', HOOKS, MOBILE, 'the invoice event now carries a currency field, three letters, always upper case.', 4 * HOUR),
    msg('s2', 't-schema', MOBILE, HOOKS, 'thanks, the phone client reads it now. shipped in the next build.', 3 * HOUR),
  ],
  't-infra': [
    msg('i1', 't-infra', INFRA, BILLING, 'deploy script ready', 28 * HOUR),
    msg('i2', 't-infra', BILLING, INFRA, 'can you add a dry run flag before friday? staging needs it.', 26 * HOUR, { status: 'expired', reason: 'receiver did not become ready within 24 hours', expect_reply: 1 }),
    notice('i-n', 't-infra', BILLING, 'your message to infra-tools expired: it did not become ready within 24 hours.', 2 * HOUR),
  ],
  't-recon': [
    msg('c1', 't-recon', RECON, BILLING, 'the nightly totals match the ledger for the last 30 days.', 5 * DAY),
  ],
  't-shots': [
    msg('p1', 't-shots', DOCS, MOBILE, 'can you send the screenshots for the push settings page?', 2 * DAY, { status: 'failed', reason: 'mobile-app closed before the message arrived', expect_reply: 1 }),
  ],
};

const PAIRS: Record<string, [Side, Side]> = {
  't-retry': [BILLING, DOCS], 't-webhooks': [BILLING, HOOKS], 't-schema': [HOOKS, MOBILE],
  't-infra': [BILLING, INFRA], 't-recon': [BILLING, RECON], 't-shots': [DOCS, MOBILE],
};

function threadRow(id: string): Record<string, unknown> {
  const rows = MESSAGES[id]!;
  const real = rows.filter((row) => row.source !== 'system');
  const last = real[real.length - 1]!;
  const [a, b] = PAIRS[id]!;
  return {
    thread: id, participants: [a, b].sort((x, y) => x.key.localeCompare(y.key)), message_count: real.length,
    last_at: Math.max(...real.map((row) => row.created_at as number)), first_at: real[0]!.created_at,
    last_preview: String(last.text).slice(0, 160), last_sender_key: last.sender_key, last_status: last.status,
  };
}

const THREADS = Object.keys(MESSAGES).map(threadRow).sort((x, y) => (y.last_at as number) - (x.last_at as number));

function listing(url: URL): unknown {
  const project = url.searchParams.get('project');
  const session = url.searchParams.get('session');
  const threads = THREADS.filter((row) => {
    const sides = row.participants as Side[];
    if (project && !sides.some((s) => String(s.project_id) === project)) return false;
    if (session && !sides.some((s) => s.id === session || s.key === session)) return false;
    return true;
  });
  return { threads, next_before: null };
}

function messages(url: URL): unknown {
  const id = decodeURIComponent(url.pathname.split('/crosstalk/threads/')[1]?.split('/')[0] ?? '');
  return { thread: id, messages: MESSAGES[id] ?? [], next_before: null };
}

export const crosstalkFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    'GET /crosstalk/threads': listing,
    'GET /crosstalk/threads/*': messages,
  },
  empty: {
    'GET /sessions/list': sessionList(),
    'GET /crosstalk/threads': { threads: [], next_before: null },
  },
};
