import { authFetch } from '../../opscenter/api/auth.svelte';
import type { FeedRun, ListSignals, RunAttachment, RunCounts, RunDelivered, RunUsage } from './logic/types';

export type {
  CounterId,
  FeedRun,
  FilesUnder,
  ListSignals,
  RecentRun,
  RunAttachment,
  RunCounts,
  RunDelivered,
  RunReadPrefs,
  RunRow,
  RunUsage,
} from './logic/types';

export type AgentEffort = 'low' | 'medium' | 'high' | 'xhigh' | 'max';

export interface AutomationTarget {
  kind: string;
  model?: string | null;
  effort?: AgentEffort | null;
  [field: string]: unknown;
}

export interface Delivery {
  notify: boolean;
  notify_on: 'always' | 'failure' | 'report' | null;
}

export interface RunSummary {
  run_id: string;
  automation_id: string;
  trigger: string;
  slot_at: number | null;
  status: string;
  reason: string | null;
  skip_count: number | null;
  first_slot_at: number | null;
  last_slot_at: number | null;
  started_at: number | null;
  ended_at: number | null;
  cost_usd: number | null;
  error: string | null;
  has_report: boolean;
  title?: string | null;
  summary?: string | null;
  number?: number;
  report_bytes?: number | null;
  attempt?: number | null;
  host?: string | null;
  output_empty?: boolean | null;
  usage?: RunUsage | null;
  delivered?: RunDelivered | null;
  attachments?: RunAttachment[] | null;
  notes?: RunNotes | null;
}

export interface RunBy extends Partial<Actor> {
  name?: string;
}

export interface RunNotes {
  by?: RunBy | null;
  [field: string]: unknown;
}

export interface Actor {
  kind: 'app' | 'mcp' | 'seed';
  session_id?: string;
  tmux?: string;
  client?: string;
}

export type Misfire = 'skip' | 'run_once';

export interface ContractFields {
  description: string;
  project_id: number | null;
  misfire: Misfire;
  retry_max: number;
  retry_backoff_s: number;
  max_runtime_s: number | null;
}

export interface Automation extends ContractFields, Partial<ListSignals> {
  automation_id: string;
  name: string;
  enabled: boolean;
  trigger: { cron: string; timezone: string };
  target: AutomationTarget;
  delivery: Delivery;
  next_fire_at: number | null;
  revision: number;
  created_at: number;
  updated_at: number;
  created_by: string;
  created_actor: Actor;
  updated_by: string;
  updated_actor: Actor;
  retry_due_at: number | null;
  last_run?: RunSummary | null;
}

export interface RecipeInfo {
  recipe: string;
  system_action?: boolean;
  params_schema: {
    properties?: Record<
      string,
      { type?: string; default?: unknown; minimum?: number; maximum?: number; minLength?: number; maxLength?: number; title?: string }
    >;
    required?: string[];
  };
}

export interface Targets {
  kinds: string[];
  recipes: RecipeInfo[];
  commands: string[];
}

export type SchedulePreview = { ok: true; fires: { utc: string; local: string }[] } | { ok: false; reason: string };

export type ParseReason =
  | 'no_ai_connection'
  | 'ai_timeout'
  | 'ai_error'
  | 'ai_output_invalid'
  | 'ai_refused'
  | 'cron_invalid'
  | 'interval_under_15_min'
  | 'never_fires'
  | 'timezone_invalid';

export interface ParsedFire {
  utc: string;
  local: string;
  in_zone: string;
}

export type ScheduleParse =
  | { ok: true; cron: string; explain?: string; fires: ParsedFire[] }
  | { ok: false; reason: ParseReason; message?: string };

export interface AutomationDraft extends Partial<ContractFields> {
  name: string;
  cron: string;
  target: AutomationTarget;
  delivery: Delivery;
  enabled: boolean;
  acknowledge_unattended?: string;
}

export interface Finding {
  finding_id: string;
  project_id: number | null;
  lever: string;
  severity: string;
  title: string;
  evidence: string;
  est_saving_usd_month: number | null;
  fix_prompt: string | null;
  source: string;
}

export interface ScroogeReportData {
  schema: string;
  generated_at: string;
  window: { start?: string; end?: string; days?: number };
  scope: { projects?: number; excluded_archived?: number; excluded_idle?: number };
  totals: { est_cost_usd: number | null; compactions: number | null; tokens?: Record<string, number | null> };
  projects: {
    project_id: number;
    name: string;
    folder: string;
    home_folder?: boolean;
    est_cost_usd: number | null;
    share_pct: number | null;
    model_mix: { model: string; share_pct: number }[];
    root_folder_only?: boolean;
    rule_files: { path: string; bytes: number; est_tokens: number; oversize: boolean }[];
  }[];
  levers: { id: string; title?: string; status: string; reason: string }[];
  findings: Finding[];
  ai: { status: string; model: string | null; cost_usd: number | null; error: string | null };
}

export interface AgentReportData {
  final_text: string;
  num_turns: number | null;
  events_seen: number;
  cost_usd: number | null;
  terminal_reason: string | null;
  subtype: string | null;
  conversation_uuid: string;
  folder: string;
}

export interface CardReportData {
  card_id: number;
  column: string;
  project_id: number;
}

export interface RunDetail extends RunSummary {
  report: ScroogeReportData | AgentReportData | CardReportData | { pruned: true } | null;
}

export interface ProjectChoice {
  name: string;
  folder: string;
  id: number | null;
}

export interface AccountChoice {
  id: string;
  name: string;
}

export interface FieldChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface AutomationChange {
  seq: number;
  automation_id: string;
  action: 'create' | 'update' | 'delete';
  at: number;
  actor: Actor;
  changes: FieldChange[];
}

export interface LogLine {
  ts: number;
  event: string;
  automation_id?: string;
  run_id?: string;
  reason?: string;
  name?: string;
  [field: string]: unknown;
}

export interface LogSettings {
  rotate: 'size' | 'daily';
  max_mb: number;
  keep: number;
}

export interface CommandList {
  commands: string[];
  max_entries: number;
  max_length: number;
}

export interface SessionChoice {
  id?: number;
  session_uuid?: string;
  tmux_name?: string;
  name?: string;
  label?: string;
  title?: string | null;
  lifecycle?: string;
  asleep?: boolean;
  project_id?: number | null;
  archived_at?: unknown;
}

export interface CreatedSession {
  id: string;
  tmux_session?: string | null;
}

const BASE = '/automations';
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export function listAutomations(): Promise<{ automations: Automation[]; scheduler: { paused: boolean }; tz?: string }> {
  return authFetch(BASE);
}

export function setSchedulerPaused(paused: boolean): Promise<{ paused: boolean }> {
  return authFetch(`${BASE}/scheduler`, json('PUT', { paused }));
}

export function listTargets(): Promise<Targets> {
  return authFetch(`${BASE}/targets`);
}

export function previewSchedule(cron: string): Promise<SchedulePreview> {
  return authFetch(`${BASE}/schedule/preview`, json('POST', { cron }));
}

export function parseSchedule(text: string, timezone: string): Promise<ScheduleParse> {
  return authFetch(`${BASE}/schedule/parse`, json('POST', { text, timezone }));
}

export function createAutomation(draft: AutomationDraft): Promise<Automation> {
  return authFetch(BASE, json('POST', draft));
}

export function updateAutomation(id: string, revision: number, changes: Partial<AutomationDraft>): Promise<Automation> {
  return authFetch(`${BASE}/${encodeURIComponent(id)}`, json('PATCH', { revision, ...changes }));
}

export function deleteAutomation(id: string): Promise<{ deleted: string }> {
  return authFetch(`${BASE}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export function runAutomationNow(id: string): Promise<RunSummary> {
  return authFetch(`${BASE}/${encodeURIComponent(id)}/run`, { method: 'POST' });
}

export function listRuns(id: string, limit = 20, opts: { before?: string; include_report?: boolean } = {}): Promise<{ runs: (RunSummary & { report?: unknown; report_omitted?: boolean })[] }> {
  const more = `${opts.before ? `&before=${encodeURIComponent(opts.before)}` : ''}${opts.include_report ? '&include=report' : ''}`;
  return authFetch(`${BASE}/${encodeURIComponent(id)}/runs?limit=${limit}${more}`);
}

export interface FeedParams {
  before?: string;
  limit?: number;
  automation_id?: string[];
  status?: string[];
  trigger?: string[];
  host?: string[];
  no_host?: boolean;
  counter?: string[];
  include_report?: boolean;
}

export function feedQuery(p: FeedParams): string {
  const q = new URLSearchParams();
  if (p.before) q.set('before', p.before);
  if (p.limit) q.set('limit', String(p.limit));
  for (const key of ['automation_id', 'status', 'trigger', 'host', 'counter'] as const) for (const v of p[key] ?? []) q.append(key, v);
  if (p.no_host) q.set('no_host', 'true');
  if (p.include_report) q.set('include', 'report');
  return q.toString();
}

export function listFeed(params: FeedParams): Promise<{ runs: FeedRun[]; total: number; next_before: string | null }> {
  return authFetch(`${BASE}/runs?${feedQuery(params)}`);
}

export function getRunCounts(): Promise<RunCounts> {
  return authFetch(`${BASE}/run-counts`);
}

export function getRun(runId: string): Promise<RunDetail> {
  return authFetch(`${BASE}/runs/${encodeURIComponent(runId)}`);
}

export function cancelRun(runId: string): Promise<RunSummary> {
  return authFetch(`${BASE}/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' });
}

export function continueRun(runId: string): Promise<CreatedSession> {
  return authFetch(`${BASE}/runs/${encodeURIComponent(runId)}/continue`, { method: 'POST' });
}

export function fixFinding(runId: string, findingId: string): Promise<CreatedSession> {
  return authFetch(`${BASE}/runs/${encodeURIComponent(runId)}/findings/${encodeURIComponent(findingId)}/fix`, { method: 'POST' });
}

export async function listProjectChoices(): Promise<ProjectChoice[]> {
  const rows = await authFetch<{ id?: number | null; name: string; root?: string | null; path: string }[] | null>('/projects');
  return (Array.isArray(rows) ? rows : []).map((row) => ({ id: row.id ?? null, name: row.name, folder: row.root || row.path })).sort((a, b) => a.name.localeCompare(b.name));
}

export async function listClaudeLogins(): Promise<AccountChoice[]> {
  const rows = await authFetch<{ id: string; name: string; provider: string }[] | null>('/provider-ledger/accounts');
  return (Array.isArray(rows) ? rows : []).filter((row) => row.provider === 'claude').map((row) => ({ id: row.id, name: row.name }));
}

export async function listAnthropicKeys(): Promise<AccountChoice[]> {
  const body = await authFetch<{ connections?: { id: string; label: string; preset: string; enabled: boolean; has_key: boolean }[] } | null>('/ai/connections');
  return (body?.connections ?? []).filter((c) => c.preset === 'anthropic' && c.enabled && c.has_key).map((c) => ({ id: c.id, name: c.label }));
}

export function listChanges(id: string, limit = 20): Promise<{ changes: AutomationChange[] }> {
  return authFetch(`${BASE}/${encodeURIComponent(id)}/changes?limit=${limit}`);
}

export function readLog(automationId: string | null, limit = 100): Promise<{ lines: LogLine[]; settings: LogSettings }> {
  const filter = automationId ? `&automation_id=${encodeURIComponent(automationId)}` : '';
  return authFetch(`/automation-log?limit=${limit}${filter}`);
}

export function putLogSettings(settings: LogSettings): Promise<LogSettings> {
  return authFetch('/automation-log/settings', json('PUT', settings));
}

export function getCommands(): Promise<CommandList> {
  return authFetch('/automation-commands');
}

export function listSessionRecords(): Promise<SessionChoice[]> {
  return authFetch('/sessions/records');
}
