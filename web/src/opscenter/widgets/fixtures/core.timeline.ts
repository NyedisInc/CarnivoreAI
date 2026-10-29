import { markOf } from '../../cells/timeline/fixture';
import type { ActivityRun, Bar, Gap, Mark, SessionTimeline } from '../../cells/timeline/types';
import { projectList, sessionList, TERMINAL_ROW_ID } from './made-up';
import type { WidgetFixtures } from './types';

const ROUTE = `GET /sessions/${TERMINAL_ROW_ID}/timeline`;
const NOW = '2026-10-11T19:00:00Z';

const at = (day: number, hm: string): string => `2026-10-${day}T${hm}:00Z`;

const GAPS: Gap[] = [
  { id: 'sleep:c1:1', conversation_id: 'c1', start: at(10, '14:10'), end: at(10, '14:25'), open: false },
  { id: 'sleep:c2:1', conversation_id: 'c2', start: at(10, '16:40'), end: at(10, '17:05'), open: false },
  { id: 'sleep:c4:1', conversation_id: 'c4', start: at(10, '23:30'), end: at(11, '12:45'), open: false },
  { id: 'sleep:c6:1', conversation_id: 'c6', start: at(11, '18:30'), end: null, open: true },
];

function runsOver(from: string, to: string): ActivityRun[] {
  const step = 30 * 60_000;
  const asleep = (ms: number): boolean => GAPS.some((g) => ms >= Date.parse(g.start) && ms < Date.parse(g.end ?? NOW));
  const runs: ActivityRun[] = [];
  for (let ms = Date.parse(from), i = 0; ms < Date.parse(to); ms += step, i += 1) {
    if (asleep(ms)) continue;
    const end = Math.min(ms + step, Date.parse(to));
    const busy = i % 3 !== 2;
    runs.push({ state: busy ? 'busy' : 'idle', start: new Date(ms).toISOString(), end: new Date(end).toISOString(), busy_seconds: busy ? 1320 : 0 });
  }
  return runs;
}

function bar(fields: Omit<Bar, 'activity' | 'busy_seconds' | 'level'>): Bar {
  const activity = runsOver(fields.started_at!, fields.ended_at!);
  return { ...fields, level: 'human', activity, busy_seconds: activity.reduce((s, r) => s + r.busy_seconds, 0) };
}

const split = (conversation: string, when: string) => ({ conversation, message_uuid: `m-${when}`, line: null, at: when });

const BARS: Bar[] = [
  bar({ conversation_id: 'c1', current: false, began: null, started_at: at(10, '13:00'), ended_at: at(10, '15:30') }),
  bar({ conversation_id: 'c2', current: false, started_at: at(10, '15:30'), ended_at: at(10, '18:10'),
    began: { kind: 'clear', from_conversation: 'c1', basis: 'recorded', at: at(10, '15:30'), split: null } }),
  bar({ conversation_id: 'c3', current: false, started_at: at(10, '18:10'), ended_at: at(10, '22:40'),
    began: { kind: 'rewind', from_conversation: 'c2', basis: 'recorded', at: at(10, '18:10'), split: split('c2', at(10, '17:20')) } }),
  bar({ conversation_id: 'c4', current: false, started_at: at(10, '22:40'), ended_at: at(11, '14:20'),
    began: { kind: 'fork', from_conversation: 'c3', basis: 'recorded', at: at(10, '22:40'), split: split('c3', at(10, '20:05')) } }),
  bar({ conversation_id: 'c5', current: false, started_at: at(11, '14:20'), ended_at: at(11, '16:00'),
    began: { kind: 'clear', from_conversation: 'c4', basis: 'recorded', at: at(11, '14:20'), split: null } }),
  bar({ conversation_id: 'c6', current: true, started_at: at(11, '16:00'), ended_at: NOW,
    began: { kind: 'rewind', from_conversation: 'c5', basis: 'recorded', at: at(11, '16:00'), split: split('c5', at(11, '15:15')) } }),
];

let serial = 0;
const bm = (c: string, when: string, label: string): Mark => {
  serial += 1;
  return markOf({ id: `bookmark:${serial}`, kind: 'bookmark', conversation_id: c, at: when, entry_uuid: `e${serial}`, can_peek: true, label, bookmark_id: serial, created_by: 'owner', snippet: label });
};
const compact = (c: string, when: string, tokens: number): Mark => markOf({ id: `compact:${c}:${when}`, kind: 'compact', conversation_id: c, at: when, entry_uuid: `x${when}`, can_peek: true, trigger: 'auto', pre_tokens: tokens });
const restart = (c: string, when: string): Mark => markOf({ id: `restart:${c}:${when}`, kind: 'restart', conversation_id: c, at: when });
const backup = (c: string, when: string, reason: string, turns: number, failsafe = false): Mark =>
  markOf({ id: `restore:${c}:${when}`, kind: 'restore', conversation_id: c, at: when, point_id: `p-${when}`, reason, pinned: false, failsafe, turns });

const MARKS: Mark[] = [
  restart('c1', at(10, '13:02')), bm('c1', at(10, '13:40'), 'plan the billing api'), compact('c1', at(10, '14:50'), 160_000),
  bm('c2', at(10, '15:31'), 'after the clear'), backup('c2', at(10, '16:39'), 'sleep', 22), restart('c2', at(10, '17:06')), bm('c2', at(10, '17:20'), 'the good version'),
  compact('c3', at(10, '19:00'), 140_000), bm('c3', at(10, '19:01'), 'before the migration'), backup('c3', at(10, '19:02'), 'save', 40),
  restart('c3', at(10, '19:03')), bm('c3', at(10, '19:04'), 'migration ran'), backup('c3', at(10, '19:06'), 'save', 44, true),
  bm('c3', at(10, '20:05'), 'fork point'), compact('c3', at(10, '21:30'), 120_000),
  backup('c4', at(10, '23:29'), 'sleep', 18), restart('c4', at(11, '12:46')), compact('c4', at(11, '13:30'), 150_000), bm('c4', at(11, '14:00'), 'ship the invoices'),
  bm('c5', at(11, '15:15'), 'rewind target'), compact('c5', at(11, '15:40'), 90_000),
  restart('c6', at(11, '16:01')), bm('c6', at(11, '16:20'), 'the second ask'), backup('c6', at(11, '17:00'), 'kill', 12),
  bm('c6', at(11, '18:00'), 'tests green'), bm('c6', at(11, '18:01'), 'docs updated'), bm('c6', at(11, '18:02'), 'ready for review'),
  backup('c6', at(11, '18:29'), 'sleep', 30),
];

function busySession(): SessionTimeline {
  return {
    session_uuid: 'row-uuid-redesign', session_row_id: TERMINAL_ROW_ID, family: 'claude', current_conversation: 'c6', now: NOW,
    bars: BARS, marks: MARKS, gaps: GAPS,
    attention: [
      { kind: 'question', start: at(10, '17:40'), end: at(10, '17:52') },
      { kind: 'question', start: at(10, '21:00'), end: at(10, '21:10') },
      { kind: 'startup', start: at(11, '16:00'), end: at(11, '16:02') },
      { kind: 'question', start: at(11, '18:20'), end: at(11, '18:28') },
    ],
  };
}

const PEEK = {
  conversation: 'c2', entry_uuid: 'e7', turns: 2,
  parts: [
    { entry_uuid: 'u1', role: 'user', text: 'run the invoice tests again and tell me what failed', timestamp: at(10, '17:18'), truncated: false },
    { entry_uuid: 'a1', role: 'assistant', text: 'all 214 pass now. the rounding fix held, so this is a good point to keep.', timestamp: at(10, '17:20'), truncated: false },
  ],
};

export const timelineWidgetFixtures: WidgetFixtures = {
  data: {
    [ROUTE]: busySession(),
    [`${ROUTE}/peek`]: PEEK,
    'GET /sessions/list': sessionList(),
    'GET /projects': projectList(),
  },
  empty: {
    [ROUTE]: {
      session_uuid: 'row-uuid-redesign', session_row_id: TERMINAL_ROW_ID, family: 'claude', current_conversation: 'c1', now: NOW,
      bars: [{ conversation_id: 'c1', current: true, level: 'human', began: null, started_at: at(11, '18:00'), ended_at: NOW }],
      marks: [], gaps: [], attention: [],
    },
    'GET /sessions/list': sessionList(),
    'GET /projects': projectList(),
  },
};
