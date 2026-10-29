import { t } from '../i18n/index.svelte';
import { consequenceLines, headline as actionHeadline, inUseLine } from './approval-display';
import {
  canApprove, hostName, isRemote, isStartupDialog, isStartupPrompt, itemSessionName, optionRows, optionTone, sessionNameFor,
  startupKindKey, startupReadOnlyReason, targetNameFor, type ApprovalDetailRow, type ApprovalItem, type NamedListingRow,
} from './approvals-model';
import { dialogCode, CLAUDE_HEADER } from '../code-review/dialog-code';
import { itemCode, lineRisks, type RiskId } from '../code-review/risk';

export type CardKind = 'startup' | 'bash' | 'edit' | 'permission' | 'question' | 'plan' | 'agent' | 'codex' | 'unreadable' | 'dialog';

export type CardTone = 'startup' | 'perm' | 'ask' | 'plan' | 'agent' | 'codex' | 'raw';

export type CardChip = 'beast' | 'waits' | 'mcp' | 'read_only';

export type Words = { key: string; params?: Record<string, string | number> } | { text: string };

export type FactId =
  | 'folder' | 'if_yes' | 'if_no' | 'command' | 'script' | 'file' | 'tool' | 'runs_in' | 'risk' | 'why'
  | 'choices' | 'answer' | 'otherwise' | 'screen' | 'why_none' | 'effect' | 'in_use' | 'target' | 'looks_like' | 'next';

export interface CardFact {
  id: FactId;
  value: Words[];
  full?: string;
  tone?: 'warn';
  wrap?: boolean;
}

export type CardRaw =
  | { kind: 'code'; code: string }
  | { kind: 'text'; text: string }
  | { kind: 'agent'; rows: ApprovalDetailRow[]; text: string };

export interface CardContract {
  kind: CardKind;
  tone: CardTone;
  who: string;
  where: string;
  host: string | null;
  headline: Words;
  facts: CardFact[];
  raw: CardRaw | null;
  chip: CardChip;
}

export interface CardContext {
  rows?: readonly ListingRowLike[] | null;
}

export interface ListingRowLike extends NamedListingRow {
  session?: { id?: string | null; tmux_session?: string | null; working_dir?: string | null } | null;
}

export const MAX_FACTS = 4;
export const PATH_FACT_CHARS = 44;

const STARTUP_WORDED: ReadonlySet<string> = new Set([
  'trust', 'codex_trust', 'mcp_server', 'bypass_permissions', 'external_imports', 'dev_channels',
]);
const FOLDER_SCREENS: ReadonlySet<string> = new Set(['trust', 'codex_trust', 'mcp_server', 'external_imports']);
const CODEX_REASON = /^\s*Reason:\s*(\S.*)$/m;
const BEAST_FAMILIES: ReadonlySet<string> = new Set(['claude', 'codex']);
const EDIT_TOOL = /^\s*(?:edit|write|create|update|multi ?edit)\b/i;
const BASH_TOOL = /^\s*bash\b/i;
const CUT_MARK = /(?:\.\.\.|\u2026)$/;
export const ASK_REVIEW_QUESTION = 'Ready to submit your answers?';

const OPTION_WORDS: Readonly<Record<string, string>> = {
  'yes': 'yes',
  'no': 'no',
  'exit': 'exit',
  'no, exit': 'no_exit',
  'yes, i trust this folder': 'trust_folder',
  'no, continue without these permissions': 'no_permissions',
  'yes, proceed': 'proceed',
  'yes, i accept': 'accept',
  'no, cancel': 'cancel',
};

export function midCut(text: string, max: number = PATH_FACT_CHARS): string {
  if (text.length <= max) return text;
  const head = Math.ceil(max * 0.4);
  const tail = max - head - 3;
  return `${text.slice(0, head)}...${text.slice(text.length - tail)}`;
}

function agentOf(item: ApprovalItem): string {
  return item.family === 'codex' ? 'codex' : 'claude';
}

function folderOf(item: ApprovalItem, rows: readonly ListingRowLike[]): string {
  const row = rows.find((r) => r.session?.id === item.session_id)
    ?? (item.tmux_session ? rows.find((r) => (r.tmux_session ?? r.session?.tmux_session) === item.tmux_session) : undefined);
  return row?.session?.working_dir?.trim() ?? '';
}

function pathFact(id: FactId, path: string): CardFact {
  return { id, value: [{ text: midCut(path) }], full: path };
}

function sayFact(id: FactId, key: string, params?: Record<string, string | number>): CardFact {
  return { id, value: [{ key, params }], wrap: true };
}

function squashed(text: string): string {
  return text.replace(/\s+/g, ' ').trim().toLowerCase();
}

function isClaudeHeader(item: ApprovalItem, tool: string): boolean {
  if (!tool) return false;
  if (CLAUDE_HEADER.test(tool)) return true;
  const question = squashed(item.question ?? '');
  const head = squashed(tool.replace(CUT_MARK, ''));
  if (!head) return false;
  return !question || !question.startsWith(head);
}

function toolHeader(item: ApprovalItem): string {
  const summary = item.summary ?? '';
  const colon = summary.indexOf(': ');
  if (summary) {
    const tool = (colon >= 0 ? summary.slice(0, colon) : summary).trim();
    return isClaudeHeader(item, tool) ? tool : '';
  }
  return (item.body ?? '').split('\n').find((line) => CLAUDE_HEADER.test(line))?.trim() ?? '';
}

function summaryTarget(item: ApprovalItem): string {
  const summary = item.summary ?? '';
  const colon = summary.indexOf(': ');
  return colon >= 0 ? summary.slice(colon + 2).trim() : '';
}

function codeRisks(code: string): RiskId[] {
  const out: RiskId[] = [];
  for (const line of code.split('\n')) for (const id of lineRisks(line)) if (!out.includes(id)) out.push(id);
  return out;
}

function commandFacts(item: ApprovalItem, code: string, folder: string): CardFact[] {
  const lines = code.split('\n').filter((line) => line.trim());
  const first = summaryTarget(item) || lines[0]?.trim() || '';
  const facts: CardFact[] = [];
  if (lines.length > 1) facts.push({ id: 'script', value: [{ key: 'approvals.card.v.lines', params: { count: lines.length } }] });
  else if (first) facts.push({ id: 'command', value: [{ text: first }], full: first });
  if (folder) facts.push(pathFact('runs_in', folder));
  const risks = codeRisks(code);
  if (risks.length) facts.push({ id: 'risk', value: risks.map((id) => ({ key: `code_review.risk.${id}` })), tone: 'warn' });
  return facts;
}

export function beastWouldAnswer(item: ApprovalItem): boolean {
  return canApprove(item) && !isStartupDialog(item) && !isRemote(item) && (item.tabs?.length ?? 0) === 0
    && BEAST_FAMILIES.has(item.family || 'claude');
}

export function optionWords(label: string): Words {
  const id = OPTION_WORDS[label.trim().toLowerCase()];
  return id ? { key: `approvals.card.option.${id}` } : { text: label };
}

export function cardOptionTone(item: ApprovalItem, label: string): 'danger' | 'confirm' | 'secondary' {
  if (optionTone(label) === 'danger') return 'danger';
  return isStartupDialog(item) && /^yes\b/i.test(label.trim()) ? 'confirm' : 'secondary';
}

function isAskReview(item: ApprovalItem): boolean {
  return item.kind === 'ask_user_question' && (item.tabs?.length ?? 0) === 0 && (item.question ?? '').trim() === ASK_REVIEW_QUESTION;
}

export function askReviewKey(sessionId: string): string {
  return `${sessionId}:ask-review`;
}

export function foldKey(item: ApprovalItem): string {
  const tabs = item.tabs ?? [];
  if (!item.session_id) return item.id;
  if (tabs.length > 0) return `${item.session_id}:ask:${tabs.map((tab) => tab.title).join('|')}`;
  return isAskReview(item) ? askReviewKey(item.session_id) : item.id;
}

function startupDialogCard(item: ApprovalItem, who: string, folder: string): Pick<CardContract, 'kind' | 'tone' | 'headline' | 'facts' | 'raw' | 'chip'> {
  const screen = item.startup_kind ?? '';
  const worded = STARTUP_WORDED.has(screen) ? screen : 'other';
  const agent = agentOf(item);
  const facts: CardFact[] = [];
  if (folder && FOLDER_SCREENS.has(screen)) facts.push(pathFact('folder', folder));
  else facts.push({ id: 'screen', value: [{ key: startupKindKey(screen) }] });
  if (worded !== 'other') facts.push(sayFact('if_yes', `approvals.card.v.yes_${worded}`, { agent }));
  if (optionRows(item).some((row) => optionTone(row.label) === 'danger')) facts.push(sayFact('if_no', 'approvals.card.v.no_exits', { agent }));
  return {
    kind: 'startup', tone: 'startup', chip: 'waits', facts,
    headline: { key: `approvals.card.hl.startup_${worded}`, params: { who, agent } },
    raw: item.body?.trim() ? { kind: 'text', text: item.body } : null,
  };
}

function permissionCard(item: ApprovalItem, who: string, folder: string): Pick<CardContract, 'kind' | 'tone' | 'headline' | 'facts' | 'raw'> {
  const tool = toolHeader(item);
  const code = itemCode(item) ?? '';
  const raw: CardRaw | null = code ? { kind: 'code', code } : item.body?.trim() ? { kind: 'text', text: item.body } : null;
  if (EDIT_TOOL.test(tool)) {
    const file = summaryTarget(item) || code.split('\n').find((line) => line.trim())?.trim() || '';
    const facts: CardFact[] = file ? [pathFact('file', file)] : [];
    if (folder) facts.push(pathFact('runs_in', folder));
    return { kind: 'edit', tone: 'perm', headline: { key: 'approvals.card.hl.edit', params: { who } }, facts, raw };
  }
  if (BASH_TOOL.test(tool) || (!tool && code)) {
    const lines = code.split('\n').filter((line) => line.trim()).length;
    const key = lines > 1 ? 'approvals.card.hl.script' : 'approvals.card.hl.bash';
    return { kind: 'bash', tone: 'perm', headline: { key, params: { who, count: lines } }, facts: commandFacts(item, code, folder), raw };
  }
  const named = tool.toLowerCase();
  const facts: CardFact[] = named ? [{ id: 'tool', value: [{ text: named }] }] : [];
  const what = summaryTarget(item);
  if (what) facts.push({ id: 'target', value: [{ text: what }], full: what });
  if (folder) facts.push(pathFact('runs_in', folder));
  return {
    kind: 'permission', tone: 'perm', facts, raw,
    headline: named ? { key: 'approvals.card.hl.permission', params: { who, tool: named } } : { key: 'approvals.card.hl.permission_bare', params: { who } },
  };
}

function codexCard(item: ApprovalItem, who: string, folder: string): Pick<CardContract, 'kind' | 'tone' | 'headline' | 'facts' | 'raw'> {
  const code = itemCode(item) ?? dialogCode(item);
  const facts = commandFacts(item, code, folder);
  const reason = CODEX_REASON.exec(item.body ?? '')?.[1]?.trim();
  if (reason) facts.splice(1, 0, { id: 'why', value: [{ text: reason }], wrap: true });
  return {
    kind: 'codex', tone: 'codex', facts,
    headline: { key: 'approvals.card.hl.codex', params: { who } },
    raw: code ? { kind: 'code', code } : item.body?.trim() ? { kind: 'text', text: item.body } : null,
  };
}

function agentCard(item: ApprovalItem, rows: readonly ListingRowLike[]): Pick<CardContract, 'who' | 'kind' | 'tone' | 'headline' | 'facts' | 'raw' | 'chip'> {
  const who = item.external_client || (sessionNameFor(item.caller, rows) ?? '');
  const display = item.display ?? null;
  const target = targetNameFor(item, rows) ?? '';
  const facts: CardFact[] = [];
  if (display) {
    for (const line of consequenceLines(display).slice(0, 2)) facts.push({ id: 'effect', value: [{ text: line }], wrap: true });
    const inUse = inUseLine(display);
    if (inUse) facts.push({ id: 'in_use', value: [{ text: inUse }], wrap: true, tone: display.in_use?.tone === 'alert' ? 'warn' : undefined });
  } else if (item.summary) {
    facts.push({ id: 'effect', value: [{ text: item.summary }], wrap: true });
  }
  if (target && target !== display?.name) facts.push({ id: 'target', value: [{ text: target }] });
  if (item.action) facts.push({ id: 'tool', value: [{ text: item.action }] });
  const action = display ? [actionHeadline(display), display.name].filter(Boolean).join(' ') : '';
  const whoWords = who || '';
  const headline: Words = action
    ? { key: whoWords ? 'approvals.card.hl.agent' : 'approvals.card.hl.agent_bare', params: { who: whoWords, action } }
    : { key: whoWords ? 'approvals.card.hl.agent_tool' : 'approvals.card.hl.agent_tool_bare', params: { who: whoWords, tool: item.action ?? '' } };
  const body = item.body?.trim() ? item.body : '';
  const detail = display?.detail ?? [];
  return {
    who, kind: 'agent', tone: 'agent', chip: 'mcp', headline, facts,
    raw: detail.length || body ? { kind: 'agent', rows: detail, text: body } : null,
  };
}

export function cardContract(item: ApprovalItem, ctx: CardContext = {}): CardContract {
  const rows = Array.isArray(ctx.rows) ? ctx.rows : [];
  const base = { who: itemSessionName(item), where: item.project ?? '', host: isRemote(item) ? hostName(item) : null };
  const folder = folderOf(item, rows);
  const who = base.who;
  const chip: CardChip = beastWouldAnswer(item) ? 'beast' : 'waits';
  let card: Pick<CardContract, 'kind' | 'tone' | 'headline' | 'facts' | 'raw'> & Partial<Pick<CardContract, 'who' | 'chip'>>;
  if (item.source === 'agent_action') {
    card = agentCard(item, rows);
  } else if (isStartupPrompt(item)) {
    const reason = startupReadOnlyReason(item.kind);
    card = {
      kind: 'startup', tone: 'raw', chip: 'read_only',
      headline: { key: 'approvals.card.hl.startup_readonly', params: { who } },
      facts: [{ id: 'screen', value: [{ key: startupKindKey(item.kind) }] }, sayFact('why_none', `approvals.card.v.readonly_${reason}`)],
      raw: item.body?.trim() ? { kind: 'text', text: item.body } : null,
    };
  } else if (isStartupDialog(item)) {
    card = startupDialogCard(item, who, folder);
  } else if (item.kind === 'permission') {
    card = permissionCard(item, who, folder);
  } else if (item.kind === 'codex_approval') {
    card = codexCard(item, who, folder);
  } else if (item.kind === 'ask_user_question') {
    const total = item.question_total ?? item.tabs?.length ?? 0;
    const options = optionRows(item).length;
    card = {
      kind: 'question', tone: 'ask', raw: null,
      headline: total > 1 ? { key: 'approvals.card.hl.questions', params: { who, count: total } } : { key: 'approvals.card.hl.question', params: { who } },
      facts: [
        { id: 'answer', value: [{ key: item.multi_select ? 'approvals.ask.pick_many' : 'approvals.ask.pick_one' }] },
        ...(options ? [{ id: 'choices' as const, value: [{ key: 'approvals.card.v.choices', params: { count: options } }] }] : []),
      ],
    };
  } else if (item.kind === 'plan_approval') {
    card = {
      kind: 'plan', tone: 'plan', chip: 'waits',
      headline: { key: 'approvals.card.hl.plan', params: { who } },
      facts: [sayFact('if_yes', 'approvals.card.v.yes_plan'), sayFact('otherwise', 'approvals.card.v.otherwise_plan')],
      raw: item.body?.trim() ? { kind: 'text', text: item.body } : null,
    };
  } else if (item.kind === 'unreadable') {
    card = {
      kind: 'unreadable', tone: 'raw', chip: 'read_only',
      headline: { key: 'approvals.card.hl.unreadable', params: { who } },
      facts: [sayFact('looks_like', 'approvals.card.v.agent_prompt', { agent: agentOf(item) }), sayFact('next', 'approvals.card.v.open_session')],
      raw: item.body?.trim() ? { kind: 'text', text: item.body } : null,
    };
  } else {
    const options = optionRows(item).length;
    card = {
      kind: 'dialog', tone: 'ask',
      headline: { key: 'approvals.card.hl.dialog', params: { who } },
      facts: options ? [{ id: 'choices', value: [{ key: 'approvals.card.v.choices', params: { count: options } }] }] : [],
      raw: item.body?.trim() ? { kind: 'text', text: item.body } : null,
    };
  }
  return {
    ...base, chip, ...card,
    who: card.who ?? who,
    facts: card.facts.slice(0, MAX_FACTS),
  } as CardContract;
}

export function say(words: Words): string {
  return 'text' in words ? words.text : t(words.key, words.params ?? null);
}

export function factText(fact: CardFact): string {
  return fact.value.map(say).join(', ');
}
