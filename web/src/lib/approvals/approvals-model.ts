
import { TMUX_SESSION_PREFIX } from '../product-identity';

export interface ApprovalRow {
  label: string;
  role: 'option' | 'other' | 'chat' | 'submit';
  checked?: boolean;
  description?: string;
}

export interface QuestionTab {
  title: string;
  answered: boolean;
}

export interface AskOptionDef {
  label: string;
  description?: string;
  preview?: string | null;
}

export interface AskQuestionDef {
  header?: string;
  question: string;
  multi_select: boolean;
  options: AskOptionDef[];
}

export interface ApprovalItem {
  id: string;
  source: 'dialog' | 'agent_action' | 'startup_prompt';
  host?: string;
  host_label?: string | null;
  session_id?: string;
  session_name?: string | null;
  project?: string | null;
  family?: string | null;
  kind?: string;
  question?: string;
  rows?: ApprovalRow[];
  multi_select?: boolean;
  has_other?: boolean;
  fingerprint?: string;
  question_index?: number | null;
  question_total?: number | null;
  tabs?: QuestionTab[];
  questions?: AskQuestionDef[];
  questions_fingerprint?: string | null;
  questions_state?: 'matched' | 'no_transcript' | 'no_questions' | 'mismatch' | null;
  body?: string;
  plain_yes?: string | null;
  plain_no?: string | null;
  startup_kind?: string | null;
  created_at?: number | string | null;
  caller?: string;
  external_client?: string;
  tmux_session?: string;
  action?: string;
  summary?: string | null;
  args?: Record<string, unknown> | null;
  confirm_text?: string | null;
  display?: ApprovalDisplay | null;
}

export interface ApprovalConsequence {
  key: string;
  params?: Record<string, string>;
}

export interface ApprovalDetailRow {
  key: string;
  value: string;
}

export interface ApprovalDisplay {
  verb: string;
  object: string;
  name: string;
  tone: 'danger' | 'confirm';
  consequences: ApprovalConsequence[];
  detail: ApprovalDetailRow[];
  in_use?: { tone: 'alert' | 'quiet'; parts: ApprovalConsequence[] };
}

export type DialogChoice =
  | { option: string }
  | { options: string[] }
  | { other: string }
  | { dismiss: true }
  | { plain: 'yes' | 'no' };

export const APPROVALS_FRAME = 'approvals';

export const STARTUP_PROMPT_SOURCE = 'startup_prompt';

export function isStartupPrompt(item: ApprovalItem): boolean {
  return item.source === STARTUP_PROMPT_SOURCE;
}

const STARTUP_KINDS: ReadonlySet<string> = new Set([
  'trust', 'oauth_login', 'codex_trust', 'external_imports', 'mcp_server', 'bypass_permissions',
  'resume_picker', 'onboarding_theme', 'login_method', 'dev_channels', 'chrome_extension', 'unrecognized',
]);

export function startupKindKey(kind: string | undefined): string {
  return `approvals.startup.kind.${kind && STARTUP_KINDS.has(kind) ? kind : 'unrecognized'}`;
}

export type StartupReadOnlyReason = 'browser' | 'picker' | 'unread';

const BROWSER_KINDS: ReadonlySet<string> = new Set(['oauth_login', 'login_method']);
const PICKER_KINDS: ReadonlySet<string> = new Set(['resume_picker', 'onboarding_theme']);

export function startupReadOnlyReason(kind: string | undefined): StartupReadOnlyReason {
  if (kind && BROWSER_KINDS.has(kind)) return 'browser';
  if (kind && PICKER_KINDS.has(kind)) return 'picker';
  return 'unread';
}

export function isStartupDialog(item: ApprovalItem): boolean {
  return item.source === 'dialog' && typeof item.startup_kind === 'string' && item.startup_kind !== '';
}

export function offersDismiss(item: ApprovalItem): boolean {
  return item.source === 'dialog' && !isStartupDialog(item);
}

export type OptionTone = 'secondary' | 'danger';

const QUITS = /^(?:no,\s*)?exit$/i;

export function optionTone(label: string): OptionTone {
  return QUITS.test(label.trim()) ? 'danger' : 'secondary';
}

/* permission prompt */
export function canApprove(item: ApprovalItem): boolean {
  return item.source === 'dialog' && typeof item.plain_yes === 'string' && item.plain_yes.trim() !== '';
}

export function optionRows(item: ApprovalItem): ApprovalRow[] {
  return (item.rows ?? []).filter((row) => row.role === 'option');
}

export function isRemote(item: ApprovalItem): boolean {
  return item.host !== undefined && item.host !== 'local' && item.host !== '';
}

/* label: ' */
export function hostName(item: ApprovalItem): string {
  const label = item.host_label?.trim();
  const key = item.host ?? '';
  if (label && label.toLowerCase() !== key.toLowerCase()) return label;
  return key.length > 13 ? `${key.slice(0, 13)}...` : key;
}

export function answerBody(item: ApprovalItem, choice: DialogChoice): { fingerprint: string; choice: DialogChoice } {
  return { fingerprint: item.fingerprint ?? '', choice };
}

export function refusalReason(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const detail = (payload as Record<string, unknown>)['detail'];
  if (!detail || typeof detail !== 'object') return null;
  const reason = (detail as Record<string, unknown>)['reason'];
  return typeof reason === 'string' && reason ? reason : null;
}

export function badgeCount(count: number): number | null {
  return Number.isFinite(count) && count > 0 ? Math.floor(count) : null;
}

export function createdMs(item: ApprovalItem): number | null {
  const raw = item.created_at;
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw < 1e12 ? raw * 1000 : raw;
  if (typeof raw === 'string' && raw) {
    const parsed = Date.parse(raw);
    return Number.isNaN(parsed) ? null : parsed;
  }
  return null;
}

export function oldestFirst(items: ApprovalItem[]): ApprovalItem[] {
  return items
    .map((item, index) => ({ item, index, at: createdMs(item) }))
    .sort((a, b) => (a.at ?? Infinity) - (b.at ?? Infinity) || a.index - b.index)
    .map((entry) => entry.item);
}

export interface NamedListingRow {
  label?: string | null;
  tmux_session?: string | null;
  session?: { tmux_session?: string | null } | null;
}

const LEGACY_TMUX_PREFIX = 'cloude_';

/* label: ' */
export function sessionNameFor(tmux: string | null | undefined, rows: readonly NamedListingRow[] | null | undefined): string | null {
  if (!tmux) return null;
  const row = (rows ?? []).find((r) => (r.tmux_session ?? r.session?.tmux_session) === tmux);
  const label = row?.label?.trim();
  if (label) return label;
  for (const prefix of [TMUX_SESSION_PREFIX, LEGACY_TMUX_PREFIX]) {
    if (tmux.startsWith(prefix) && tmux.length > prefix.length) return tmux.slice(prefix.length);
  }
  return null;
}

export function targetNameFor(item: ApprovalItem, rows: readonly NamedListingRow[] | null | undefined): string | null {
  const given = item.session_name?.trim();
  if (given && given !== item.tmux_session) return given;
  return sessionNameFor(item.tmux_session, rows);
}

export function itemSessionName(item: ApprovalItem): string {
  return targetNameFor(item, null) ?? item.session_name ?? item.session_id ?? '';
}

export interface DiffRow {
  field: string;
  before?: unknown;
  after?: unknown;
}

export function diffRows(item: Pick<ApprovalItem, 'args'>): DiffRow[] {
  const raw = item.args?.diff;
  if (!Array.isArray(raw)) return [];
  return raw.filter((row): row is DiffRow => !!row && typeof row === 'object' && typeof (row as DiffRow).field === 'string');
}

export function diffValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export const ASK_TEXT_MAX = 2000;

export interface AskDraft {
  choice: number | null;
  picks: number[];
  other: string;
  useOther: boolean;
  notes: string;
}

export function emptyDraft(): AskDraft {
  return { choice: null, picks: [], other: '', useOther: false, notes: '' };
}

export interface AskAnswerBody {
  option?: string;
  options?: string[];
  other?: string;
  notes?: string;
}

export function hasPreview(question: AskQuestionDef): boolean {
  return question.options.some((option) => !!option.preview);
}

export function hasOtherRow(question: AskQuestionDef): boolean {
  return !hasPreview(question);
}

export function isAnswered(question: AskQuestionDef, draft: AskDraft): boolean {
  const other = draft.other.trim() !== '';
  if (question.multi_select) return draft.picks.length > 0 || other;
  return draft.useOther ? other : draft.choice !== null;
}

export function answerFor(question: AskQuestionDef, draft: AskDraft): AskAnswerBody {
  if (!isAnswered(question, draft)) return {};
  const other = draft.other.trim();
  if (question.multi_select) {
    const labels = question.options.filter((_, i) => draft.picks.includes(i)).map((option) => option.label);
    return other ? { options: labels, other } : { options: labels };
  }
  if (draft.useOther) return { other };
  const notes = draft.notes.trim();
  const option = question.options[draft.choice as number]!.label;
  return hasPreview(question) && notes ? { option, notes } : { option };
}

export function isUnsupportedAnswer(question: AskQuestionDef, draft: AskDraft): boolean {
  return question.multi_select && hasPreview(question) && isAnswered(question, draft);
}

export function unansweredCount(questions: AskQuestionDef[], drafts: AskDraft[]): number {
  return questions.filter((q, i) => !isAnswered(q, drafts[i] ?? emptyDraft())).length;
}

export function isQuestionItem(item: ApprovalItem): boolean {
  return item.source === 'dialog' && item.kind === 'ask_user_question';
}

export function isWholeAsk(item: ApprovalItem): boolean {
  return item.source === 'dialog' && item.kind === 'ask_user_question' && item.questions_state === 'matched'
    && (item.questions?.length ?? 0) > 0 && !!item.questions_fingerprint && !isStartupDialog(item);
}
