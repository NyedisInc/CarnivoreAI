
export const ACTIVITY_STATUSES = [
  'working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead', 'unknown',
] as const;

export type ActivityStatus = (typeof ACTIVITY_STATUSES)[number];

export const STATUS = {
  working: 'working', working_subagent: 'working_subagent', question: 'question', notice: 'notice',
  finished_unread: 'finished_unread', idle: 'idle', dead: 'dead', unknown: 'unknown',
} as const satisfies Record<ActivityStatus, ActivityStatus>;

export const BUSY: ReadonlySet<string> = new Set<ActivityStatus>(['working', 'working_subagent']);

export const RESTING: ReadonlySet<string> = new Set<ActivityStatus>(['idle', 'finished_unread']);

export const ASKING: ReadonlySet<string> = new Set<ActivityStatus>(['question', 'notice']);

export const BLOCKED_ON_OWNER: ReadonlySet<string> = new Set<ActivityStatus>(['question']);

export const TURN_OVER: ReadonlySet<string> = new Set<ActivityStatus>([...RESTING, ...ASKING] as ActivityStatus[]);

export function isActivityStatus(value: unknown): value is ActivityStatus {
  return typeof value === 'string' && (ACTIVITY_STATUSES as readonly string[]).includes(value);
}
