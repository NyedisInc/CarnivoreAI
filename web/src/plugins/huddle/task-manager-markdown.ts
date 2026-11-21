
export const MD_MAX_CHARS = 20000;

export type MdInline =
  | { t: 'text'; v: string }
  | { t: 'strong'; c: MdInline[] }
  | { t: 'em'; c: MdInline[] }
  | { t: 'code'; v: string }
  | { t: 'link'; href: string; c: MdInline[] };

export type MdAlign = 'left' | 'right' | 'center';

export interface MdListItem {
  c: MdInline[];
  sub?: { ordered: boolean; items: MdInline[][] };
}

export type MdBlock =
  | { t: 'paragraph'; lines: MdInline[][] }
  | { t: 'heading'; level: 1 | 2; c: MdInline[] }
  | { t: 'code'; text: string; lang: string; full?: string }
  | { t: 'list'; ordered: boolean; start: number; items: MdListItem[] }
  | { t: 'table'; head: MdInline[][]; align: MdAlign[]; rows: MdInline[][][] }
  | { t: 'kv'; pairs: { k: string; v: MdInline[] }[] };

const FENCE = /^```\s*([A-Za-z0-9_-]*)\s*$/;
const HEADING = /^(#{1,2})\s+(\S.*)$/;
const LIST_ITEM = /^(\s*)([-*+]|\d{1,3}[.)])\s+(\S.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
const KV_LINE = /^\s*([^:\n]{1,40}?)\s*:\s+(\S.*)$/;
const NUMBER_CELL = /^[-+]?[$€£]?\d[\d,]*(\.\d+)?%?$|^[-+]?[$€£]?\.\d+%?$/;
const INLINE = /`([^`\n]+)`|\*\*\*\s*(\S(?:[^]*?\S)?)\s*\*\*\*|\*\*\s*(\S(?:[^]*?\S)?)\s*\*\*|\*([^\s*](?:[^*]*[^\s*])?)\*|\[([^\]\n]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>)\]]+)/g;

export function safeHref(raw: string): string | null {
  try {
    const url = new URL(raw);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch {
    return null;
  }
}

function parseRaw(text: string, allowLinks: boolean): MdInline[] {
  const out: MdInline[] = [];
  let last = 0;
  const push = (v: string): void => { if (v) out.push({ t: 'text', v }); };
  for (const m of text.matchAll(INLINE)) {
    const at = m.index ?? 0;
    const [raw, code, both, bold, ital, label, target, bare] = m;
    let node: MdInline | null = null;
    if (code !== undefined) node = { t: 'code', v: code };
    else if (both !== undefined) node = { t: 'strong', c: [{ t: 'em', c: parseRaw(both, allowLinks) }] };
    else if (bold !== undefined) node = { t: 'strong', c: parseRaw(bold, allowLinks) };
    else if (ital !== undefined) node = { t: 'em', c: parseRaw(ital, allowLinks) };
    else if (label !== undefined && allowLinks) {
      const href = safeHref(target ?? '');
      if (href) node = { t: 'link', href, c: parseRaw(label, false) };
    } else if (bare !== undefined && allowLinks) {
      const trimmed = bare.replace(/[.,;:!?]+$/, '');
      const href = safeHref(trimmed);
      if (href) {
        push(text.slice(last, at));
        out.push({ t: 'link', href, c: [{ t: 'text', v: trimmed }] });
        last = at + trimmed.length;
        continue;
      }
    }
    if (!node) continue;
    push(text.slice(last, at));
    out.push(node);
    last = at + raw.length;
  }
  push(text.slice(last));
  return out;
}

const MASK_OPEN = '\uE000';
const MASK_CLOSE = '\uE001';
const CODE_SPAN = /`([^`\n]+)`/g;
const MASK_RE = new RegExp(`${MASK_OPEN}(\\d+)${MASK_CLOSE}`, 'g');

function unmask(nodes: MdInline[], spans: string[]): MdInline[] {
  const out: MdInline[] = [];
  for (const node of nodes) {
    if (node.t === 'text') {
      let last = 0;
      for (const m of node.v.matchAll(MASK_RE)) {
        const at = m.index ?? 0;
        if (at > last) out.push({ t: 'text', v: node.v.slice(last, at) });
        out.push({ t: 'code', v: spans[Number(m[1])] ?? '' });
        last = at + m[0].length;
      }
      if (last < node.v.length) out.push({ t: 'text', v: node.v.slice(last) });
    } else if (node.t === 'link') {
      out.push({ ...node, href: node.href.replace(MASK_RE, (_all, i) => '`' + (spans[Number(i)] ?? '') + '`'), c: unmask(node.c, spans) });
    } else if (node.t === 'code') {
      out.push(node);
    } else {
      out.push({ ...node, c: unmask(node.c, spans) });
    }
  }
  return out;
}

export function parseInline(text: string, allowLinks = true): MdInline[] {
  if (text.includes(MASK_OPEN) || !text.includes('`')) return parseRaw(text, allowLinks);
  const spans: string[] = [];
  const masked = text.replace(CODE_SPAN, (_all, code: string) => `${MASK_OPEN}${spans.push(code) - 1}${MASK_CLOSE}`);
  return unmask(parseRaw(masked, allowLinks), spans);
}

export function splitLines(nodes: MdInline[]): MdInline[][] {
  const lines: MdInline[][] = [[]];
  const add = (node: MdInline): void => { (lines[lines.length - 1] as MdInline[]).push(node); };
  for (const node of nodes) {
    if (node.t === 'code') { add(node); continue; }
    if (node.t === 'text') {
      node.v.split('\n').forEach((part, i) => { if (i > 0) lines.push([]); if (part) add({ t: 'text', v: part }); });
      continue;
    }
    splitLines(node.c).forEach((part, i) => { if (i > 0) lines.push([]); if (part.length) add({ ...node, c: part }); });
  }
  return lines;
}

function splitRow(line: string): string[] {
  let body = line.trim();
  if (body.startsWith('|')) body = body.slice(1);
  if (body.endsWith('|') && !body.endsWith('\\|')) body = body.slice(0, -1);
  return body.split(/(?<!\\)\|/).map((cell) => cell.replace(/\\\|/g, '|').trim());
}

function sepAlign(cell: string): MdAlign | null {
  const left = cell.startsWith(':');
  const right = cell.endsWith(':');
  if (left && right) return 'center';
  if (right) return 'right';
  return left ? 'left' : null;
}

function parseTable(lines: string[], at: number): { block: MdBlock; next: number } | null {
  const headLine = lines[at] ?? '';
  const sepLine = lines[at + 1];
  if (!headLine.includes('|') || sepLine === undefined || !sepLine.includes('-') || !TABLE_SEP.test(sepLine)) return null;
  const head = splitRow(headLine);
  const seps = splitRow(sepLine);
  if (head.length !== seps.length || head.length === 0) return null;
  const rowsRaw: string[][] = [];
  let next = at + 2;
  while (next < lines.length && (lines[next] ?? '').includes('|') && (lines[next] ?? '').trim() !== '') {
    const cells = splitRow(lines[next] ?? '');
    if (cells.length !== head.length) return null;
    rowsRaw.push(cells);
    next += 1;
  }
  const align: MdAlign[] = head.map((_, col) => {
    const explicit = sepAlign(seps[col] ?? '');
    if (explicit) return explicit;
    const cells = rowsRaw.map((row) => row[col] ?? '').filter((cell) => cell !== '');
    return cells.length > 0 && cells.every((cell) => NUMBER_CELL.test(cell)) ? 'right' : 'left';
  });
  return {
    block: { t: 'table', head: head.map((c) => parseInline(c)), align, rows: rowsRaw.map((row) => row.map((c) => parseInline(c))) },
    next,
  };
}

function parseList(lines: string[], at: number): { block: MdBlock; next: number } {
  const first = LIST_ITEM.exec(lines[at] ?? '');
  const base = first?.[1]?.length ?? 0;
  const items: MdListItem[] = [];
  const ordered = /^\d/.test(first?.[2] ?? '');
  const start = ordered ? Math.max(0, parseInt(first?.[2] ?? '1', 10)) : 1;
  let next = at;
  while (next < lines.length) {
    if ((lines[next] ?? '').trim() === '' && items.length > 0) {
      const after = LIST_ITEM.exec(lines[next + 1] ?? '');
      const continues = after && ((after[1] ?? '').length > base || /^\d/.test(after[2] ?? '') === ordered);
      if (!continues) break;
      next += 1;
    }
    const m = LIST_ITEM.exec(lines[next] ?? '');
    if (!m) break;
    const depth = (m[1] ?? '').length;
    const isOrdered = /^\d/.test(m[2] ?? '');
    const inline = parseInline(m[3] ?? '');
    if (depth > base && items.length > 0) {
      const parent = items[items.length - 1] as MdListItem;
      parent.sub ??= { ordered: isOrdered, items: [] };
      parent.sub.items.push(inline);
    } else {
      items.push({ c: inline });
    }
    next += 1;
  }
  return { block: { t: 'list', ordered, start, items }, next };
}

function parseFence(lines: string[], at: number): { block: MdBlock; next: number } {
  const lang = FENCE.exec(lines[at] ?? '')?.[1] ?? '';
  const body: string[] = [];
  let next = at + 1;
  while (next < lines.length && !FENCE.test(lines[next] ?? '')) {
    body.push(lines[next] ?? '');
    next += 1;
  }
  next += 1;
  if (lang.toLowerCase() === 'kv') {
    const pairs: { k: string; v: MdInline[] }[] = [];
    for (const line of body.filter((l) => l.trim() !== '')) {
      const m = KV_LINE.exec(line);
      if (!m) { pairs.length = 0; break; }
      pairs.push({ k: m[1] ?? '', v: parseInline(m[2] ?? '') });
    }
    if (pairs.length > 0) return { block: { t: 'kv', pairs }, next };
  }
  return { block: { t: 'code', text: body.join('\n'), lang }, next };
}

function startsBlock(lines: string[], at: number): boolean {
  const line = lines[at] ?? '';
  return line.trim() === '' || FENCE.test(line) || HEADING.test(line) || LIST_ITEM.test(line) || parseTable(lines, at) !== null;
}

const LINE_MARK = /^\s*(?:#{1,6}\s+|[-*+]\s+|\d{1,3}[.)]\s+|>\s?)/;

export function parseLine(text: string): MdInline[] {
  if (text.length > MD_MAX_CHARS) return [{ t: 'text', v: text }];
  const kept: string[] = [];
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    if (FENCE.test(raw) || (raw.includes('-') && TABLE_SEP.test(raw))) continue;
    const line = raw.replace(LINE_MARK, '').trim();
    if (line) kept.push(line);
  }
  return parseInline(kept.join(' '));
}

export function plainOf(nodes: MdInline[]): string {
  return nodes.map((node) => (node.t === 'text' || node.t === 'code' ? node.v : plainOf(node.c))).join('');
}

export function mdPlain(text: string): string {
  return plainOf(parseLine(text));
}

export function parseMarkdown(text: string): MdBlock[] {
  if (text.length > MD_MAX_CHARS) return [{ t: 'paragraph', lines: [[{ t: 'text', v: text }]] }];
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const blocks: MdBlock[] = [];
  let at = 0;
  while (at < lines.length) {
    const line = lines[at] ?? '';
    if (line.trim() === '') { at += 1; continue; }
    if (FENCE.test(line)) {
      const r = parseFence(lines, at);
      blocks.push(r.block);
      at = r.next;
      continue;
    }
    const heading = HEADING.exec(line);
    if (heading) {
      blocks.push({ t: 'heading', level: heading[1]?.length === 1 ? 1 : 2, c: parseInline(heading[2] ?? '') });
      at += 1;
      continue;
    }
    const table = parseTable(lines, at);
    if (table) { blocks.push(table.block); at = table.next; continue; }
    if (LIST_ITEM.test(line)) {
      const r = parseList(lines, at);
      blocks.push(r.block);
      at = r.next;
      continue;
    }
    const para: string[] = [line];
    at += 1;
    while (at < lines.length && !startsBlock(lines, at)) {
      para.push(lines[at] ?? '');
      at += 1;
    }
    blocks.push({ t: 'paragraph', lines: splitLines(parseInline(para.join('\n'))) });
  }
  return blocks;
}
