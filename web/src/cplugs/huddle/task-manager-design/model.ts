import type { HuddleItem, TaskManagerMessage } from '../huddle-model';
import type { Closure } from './closed-api';
import type { Shared } from './task-view';
export type TaskState = 'open' | 'working' | 'question' | 'review' | 'waiting' | 'later' | 'closed';
export type Surface = 'main' | 'quick' | 'closed';
export type Tab = 'action' | 'discussion' | 'details' | 'subtasks';
export interface Message {
  id?: string; by: 'you' | 'agent'; time: string; text: string; read?: boolean;
  kind?: string; quote?: string; event?: boolean; system?: boolean; comment?: boolean; answered?: boolean; sharedIds?: string[];
}
export interface Resource {
  id: string; type?: string; icon?: string; kind?: string; name: string; rev?: string; source?: number;
  text?: string; href?: string; image?: string; unavailable?: boolean; reason?: string;
  versions?: { rev: string; label: string; text: string }[];
  shared?: Shared;
}
export interface ReviewCheck {
  id: string; label: string; resourceId?: string; resourceRev?: string; guidance?: string;
  checked: boolean; version: number; note?: string;
}
export interface Review {
  version: number; run?: string; resources: Resource[]; checks: ReviewCheck[]; history: string[];
  where?: string; link?: string;
}
export interface Schedule {
  kind: 'once' | 'daily' | 'weekly' | 'hours' | 'monthly'; when: string; paused: boolean;
  days: number[]; hours: number; monthday: number; last?: string;
}
export interface Question { text: string; options: string[] }
export interface Task {
  id: number; title: string; project: string; state: TaskState; agent: string; text: string;
  age?: string; original?: string; messages: Message[]; shared?: Resource[]; questions?: Question[];
  review?: Review; schedule?: Schedule; previousSchedule?: Schedule | null; note?: string; parent?: number;
  outcome?: 'completed' | 'cancelled'; closedAt?: number; closedLabel?: string; closedBy?: string; prior?: TaskState; delivery?: string;
  blocker?: { summary: string; reason: string; owner: string; condition: string; source: number };
  workPlan?: { phase: string; source: string; updated: string; steps: { text: string; status: string }[] };
  githubIssue?: { url: string; repo: string; number: number; title: string };
  list?: string;
  asks?: TaskManagerMessage[];
  item?: HuddleItem;
  unread?: boolean;
  scheduled?: boolean;
  canUndo?: boolean;
  closure?: Closure;
}
export interface Draft { text: string; mode: 'reply' | 'comment'; values: Record<number, number> }
export interface Inspection { tab: Tab; earlier: boolean; approved: boolean; scroll: number; boundary: number }
export const STATES: TaskState[] = ['question', 'review', 'working', 'waiting', 'open', 'later'];
export const STATE_ICON: Record<TaskState, string> = {
  open: 'status-idle', working: 'status-working', question: 'status-question', review: 'status-review', waiting: 'hourglass', later: 'archive', closed: 'check',
};
export const unread = (task: Task): boolean => task.messages.some(m => m.by === 'agent' && !m.read);
export const newCount = (task: Task): number => task.messages.filter(m => m.by === 'agent' && !m.read).length;
export const matches = (task: Task, text: string): boolean =>
  [task.title, task.project, task.agent, task.text].join(' ').toLowerCase().includes(text.trim().toLowerCase());
export function webLink(value?: string): string | undefined {
  if (!value) return undefined;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; }
}
