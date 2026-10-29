import type { ApprovalItem } from '../approvals/approvals-model';
import { dialogCode } from './dialog-code';

export type RiskId = 'delete' | 'sudo' | 'pipe_shell' | 'perms' | 'outside_write' | 'credentials' | 'force' | 'disk' | 'kill';

export interface RiskRule {
  id: RiskId;
  pattern: RegExp;
}

export const RISK_RULES: readonly RiskRule[] = [
  { id: 'delete', pattern: /\b(rm|rmdir|unlink|shred|trash)\s/i },
  { id: 'delete', pattern: /\bfind\b.*\s-delete\b/i },
  { id: 'delete', pattern: /\bgit\s+(clean|checkout\s+--|restore)\b/i },
  { id: 'delete', pattern: /\b(drop|truncate)\s+(table|database|schema)\b/i },
  { id: 'sudo', pattern: /\b(sudo|doas)\b/i },
  { id: 'pipe_shell', pattern: /\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b/i },
  { id: 'pipe_shell', pattern: /\b(ba|z)?sh\s+<\(\s*(curl|wget)\b/i },
  { id: 'pipe_shell', pattern: /\beval\b.*\b(curl|wget)\b/i },
  { id: 'perms', pattern: /\bch(mod|own|grp)\b.*(\s-\w*R|\s-R\b|\b777\b|\ba\+[rwx]*w|\bo\+[rwx]*w|\s(\/|~)(\s|$))/i },
  { id: 'outside_write', pattern: />>?\s*(?!\/dev\/(null|stdout|stderr)\b)(\/|~|\$HOME|\.\.\/)/i },
  { id: 'outside_write', pattern: /\btee\b\s+(-a\s+)?(\/|~|\$HOME)/i },
  { id: 'outside_write', pattern: /\b(cp|mv|ln|install|rsync)\b.*\s(\/|~\/|\$HOME\/)[^\s]*\s*$/i },
  { id: 'credentials', pattern: /(^|[\s/"'=])\.env(\.\w+)?\b/i },
  { id: 'credentials', pattern: /\.ssh\/|\bid_(rsa|ed25519|ecdsa|dsa)\b|\.pem\b|\.p12\b/i },
  { id: 'credentials', pattern: /\.aws\/|\.netrc\b|\.npmrc\b|\.gnupg\b|credentials\.json|\/etc\/(shadow|passwd|sudoers)/i },
  { id: 'credentials', pattern: /\bsecurity\s+(find|dump|export|delete)-?\w*|keychain|\bop\s+(read|item\s+get)\b/i },
  { id: 'force', pattern: /\bgit\s+push\b.*(\s--force\b|\s-f\b|--force-with-lease|\s\+\w)/i },
  { id: 'force', pattern: /\bgit\s+reset\s+--hard\b/i },
  { id: 'disk', pattern: /\bdd\b.*\bof=/i },
  { id: 'disk', pattern: /\bmkfs(\.\w+)?\b|\bdiskutil\s+(erase|partition|zero)\w*/i },
  { id: 'disk', pattern: />\s*\/dev\/(sd|disk|nvme|hd)\w*/i },
  { id: 'kill', pattern: /\b(kill|killall|pkill)\b/i },
];

export interface ReviewLine {
  n: number;
  text: string;
  risks: RiskId[];
}

/* permission prompt */
const CODE_KINDS: ReadonlySet<string> = new Set(['permission', 'codex_approval']);

const SCRIPT_SHAPE = /^(#!\/|\$ \S)/m;

export function lineRisks(line: string): RiskId[] {
  const hits: RiskId[] = [];
  for (const rule of RISK_RULES) {
    if (!hits.includes(rule.id) && rule.pattern.test(line)) hits.push(rule.id);
  }
  return hits;
}

export function reviewLines(code: string): ReviewLine[] {
  const lines = code.replace(/\r\n?/g, '\n').replace(/\n$/, '').split('\n');
  return lines.map((text, i) => ({ n: i + 1, text, risks: lineRisks(text) }));
}

export function visibleLines(lines: readonly ReviewLine[], riskyOnly: boolean): ReviewLine[] {
  return riskyOnly ? lines.filter((line) => line.risks.length > 0) : [...lines];
}

export function itemCode(item: ApprovalItem): string | null {
  if (item.source !== 'dialog' || item.startup_kind) return null;
  const body = item.body ?? '';
  if (!body.trim()) return null;
  if (item.kind === 'ask_user_question' || item.kind === 'unreadable' || item.kind === 'folder_trust') return null;
  const code = dialogCode(item);
  if (!code) return null;
  if (CODE_KINDS.has(item.kind ?? '')) return code;
  return SCRIPT_SHAPE.test(code) || reviewLines(code).some((line) => line.risks.length > 0) ? code : null;
}
