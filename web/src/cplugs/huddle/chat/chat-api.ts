import { authFetch } from '../../sdk';
import type { HuddleItem } from '../huddle-model';

export type SwarmAgentState = 'asleep' | 'waking' | 'awake' | 'sleeping' | 'torn_down';

export interface SwarmAgentDetail {
  id: number;
  display_name: string;
  rank: string;
  state: SwarmAgentState;
  thread_key: string;
  session_id: string | null;
  tmux_session: string | null;
  memory_scope?: string;
  host_key?: string;
  host_label?: string | null;
  placement_reason?: string | null;
}

export interface AuthorCrumb {
  kind: 'company' | 'project' | 'agent' | 'sysop' | 'owner';
  name: string;
  agent_id: number | null;
}

export interface QuestionAsker {
  agent_id: number | null;
  name: string;
  author_path?: AuthorCrumb[];
}

export interface SwarmQuestion {
  summary: string;
  task: string;
  details: string;
  askers: QuestionAsker[];
  asked_at?: number | null;
}

interface Authored {
  author_path?: AuthorCrumb[] | null;
}

export type SwarmEntry =
  | ({ kind: 'owner'; id: string; at: number; text: string } & Authored)
  | ({ kind: 'agent'; id: string; at: number; text: string; draft?: 'writing' | 'stopped' | null } & Authored)
  | ({ kind: 'card'; id: string; at: number; card: 'done' | 'question' | 'review' | 'info'; item: HuddleItem; question?: SwarmQuestion | null } & Authored)
  | (SwarmTrafficEntry & Authored)
  | (SwarmEventEntry & Authored);

export interface SwarmTrafficReceipt {
  status: 'queued' | 'held' | 'delivering' | 'delivered' | 'failed' | 'expired' | string;
  reason?: string | null;
  delivered_at?: string | number | null;
}

export interface SwarmTrafficEntry {
  kind: 'traffic';
  id: string;
  at: number;
  direction: 'in' | 'out';
  peer: string;
  peer_session_uuid?: string | null;
  text: string;
  summary?: string;
  thread?: string | null;
  in_reply_to?: string | null;
  receipt?: SwarmTrafficReceipt | null;
}

export interface ReceiptFact {
  id: string;
  title: string;
  scope: 'craft' | 'project';
  origin: 'owner' | 'agent' | 'handwritten';
  owner_message_ref: string | null;
  taught_at: string;
  state: 'live' | 'held' | 'killed';
}

export interface SwarmReceipt {
  kind: 'owner_fact' | 'agent_fact' | 'judgment' | 'owner_answer';
  rendered: string;
  owner_message_ref: string | null;
  facts: ReceiptFact[];
}

export interface SwarmEventEntry {
  kind: 'event';
  id: string;
  at: number;
  event: string;
  ref: string;
  text: string;
  receipt?: SwarmReceipt;
}

export interface SwarmConversationPage {
  entries: SwarmEntry[];
  cursor: string | null;
}

export const CONVERSATION_LIMIT = 200;

export interface SwarmMessageResponse {
  message_ref: string;
  outcome: 'delivered' | 'held' | 'waking';
}

export function readAgent(id: number): Promise<SwarmAgentDetail> {
  return authFetch<SwarmAgentDetail>(`/swarm/agents/${id}`);
}

export function readConversation(id: number): Promise<SwarmConversationPage> {
  return authFetch<SwarmConversationPage>(`/swarm/agents/${id}/conversation?limit=${CONVERSATION_LIMIT}`);
}

export function postOrder(id: number, text: string): Promise<SwarmMessageResponse> {
  return authFetch<SwarmMessageResponse>(`/swarm/agents/${id}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
}

export async function sleepAgent(id: number): Promise<void> {
  await authFetch(`/swarm/agents/${id}/sleep`, { method: 'POST' });
}

/* project leader */
export async function turnOffAgent(id: number, confirmName?: string): Promise<void> {
  await authFetch(`/swarm/agents/${id}/turn-off`, { method: 'POST', body: confirmName === undefined ? undefined : JSON.stringify({ confirm_name: confirmName }) });
}

export async function renameAgent(id: number, displayName: string): Promise<void> {
  await authFetch(`/swarm/agents/${id}/name`, { method: 'PUT', body: JSON.stringify({ display_name: displayName }) });
}

export async function wakeAgent(id: number, mode: 'fresh' | 'resume'): Promise<void> {
  await authFetch(`/swarm/agents/${id}/wake`, { method: 'POST', body: JSON.stringify({ mode }) });
}

export async function exportAgent(id: number, name: string): Promise<void> {
  const blob = await authFetch<Blob>(`/swarm/agents/${id}/export`);
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = blob instanceof File && blob.name ? blob.name : `${name.trim().replace(/[^a-z0-9._-]+/gi, '-').toLowerCase() || `agent-${id}`}-craft.zip`;
  link.rel = 'noopener';
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function killFact(factId: string): Promise<number[]> {
  const done = await authFetch<{ reopened_question_ids: number[] }>(`/swarm/facts/${factId}`, { method: 'DELETE' });
  return done.reopened_question_ids ?? [];
}

export async function retagFact(factId: string, scope: 'craft' | 'project'): Promise<void> {
  await authFetch(`/swarm/facts/${factId}`, { method: 'PATCH', body: JSON.stringify({ scope }) });
}

export interface SwarmCheckpoint {
  sha: string;
  at: string;
  subject: string;
  kind: 'memory' | 'promotion' | 'flip_back' | 'rewind' | string;
}

export interface SwarmCheckpointList {
  commits: SwarmCheckpoint[];
  reason: string | null;
}

export interface SwarmEarlierConversation {
  wake_id: number;
  conversation_uuid: string;
  started_at: string;
  reason: string | null;
  authority: string | null;
  transcript_present: boolean;
}

export function readCheckpoints(id: number): Promise<SwarmCheckpointList> {
  return authFetch<SwarmCheckpointList>(`/swarm/agents/${id}/checkpoints`);
}

export function readEarlierConversations(id: number): Promise<SwarmEarlierConversation[]> {
  return authFetch<SwarmEarlierConversation[]>(`/swarm/agents/${id}/conversations`);
}

export async function rewindAgent(id: number, sha: string): Promise<void> {
  await authFetch(`/swarm/agents/${id}/rewind`, { method: 'POST', body: JSON.stringify({ sha }) });
}

export async function resumeConversation(id: number, conversationUuid: string): Promise<void> {
  await authFetch(`/swarm/agents/${id}/wake`, { method: 'POST', body: JSON.stringify({ conversation_uuid: conversationUuid }) });
}
