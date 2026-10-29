import type { ApprovalItem } from '../approvals/approvals-model';

const NUMBERED_ROW = /^\s*[❯›>]?\s*\d+\.\s+\S/;
const ROW_PREFIX = /^\s*[❯›>]?\s*\d+\.\s+/;
export const CLAUDE_HEADER = /^\s*[A-Z][A-Za-z]*(?: [A-Za-z]+)? (?:command|file|edit|request)\s*$/i;
const TIP_LINE = /^\s*Tip:/;
const CODEX_META = /^\s*(?:Environment|Reason):/;
const TIP_CONTINUATION_MAX_INDENT = 2;

function squash(text: string): string {
  return text.replace(/\s+/g, '');
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

export function optionStart(lines: readonly string[], rows: ApprovalItem['rows']): number {
  const first = rows?.[0]?.label?.trim();
  if (first) {
    const at = lines.findIndex((l) => NUMBERED_ROW.test(l) && l.replace(ROW_PREFIX, '').startsWith(first));
    if (at >= 0) return at;
  }
  return lines.findIndex((l) => NUMBERED_ROW.test(l));
}

function questionEnd(lines: readonly string[], question: string, limit: number): { start: number; end: number } | null {
  const want = squash(question);
  if (!want) return null;
  for (let end = limit - 1; end >= 0; end--) {
    for (let span = 1; span <= 4 && end - span + 1 >= 0; span++) {
      const start = end - span + 1;
      if (squash(lines.slice(start, end + 1).join('')) === want) return { start, end };
    }
  }
  return null;
}

function tidy(lines: string[]): string[] {
  const kept = [...lines];
  while (kept.length && !(kept[0] ?? '').trim()) kept.shift();
  while (kept.length && !(kept[kept.length - 1] ?? '').trim()) kept.pop();
  const indents = kept.filter((l) => l.trim()).map(indentOf);
  const cut = indents.length ? Math.min(...indents) : 0;
  return kept.map((l) => l.slice(Math.min(cut, indentOf(l))).trimEnd());
}

function dropClaudeChrome(lines: string[]): string[] {
  const at = (n: number): string => lines[n] ?? '';
  let i = 0;
  while (i < lines.length && !at(i).trim()) i++;
  if (i < lines.length && CLAUDE_HEADER.test(at(i))) i++;
  if (i < lines.length && TIP_LINE.test(at(i))) {
    i++;
    while (i < lines.length && at(i).trim() && indentOf(at(i)) <= TIP_CONTINUATION_MAX_INDENT) i++;
  }
  return lines.slice(i);
}

/* Do you want to proceed? */
export function dialogCode(item: Pick<ApprovalItem, 'body' | 'question' | 'rows'>): string {
  let lines = (item.body ?? '').replace(/\r\n?/g, '\n').split('\n');
  const options = optionStart(lines, item.rows);
  if (options >= 0) lines = lines.slice(0, options);
  const q = questionEnd(lines, item.question ?? '', lines.length);
  if (q) {
    const after = lines.slice(q.end + 1);
    lines = after.some((l) => l.trim()) ? after : lines.slice(0, q.start);
  }
  lines = dropClaudeChrome(lines).filter((l) => !CODEX_META.test(l));
  return tidy(lines).join('\n');
}
