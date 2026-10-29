
export type Inline = { type: 'text'; text: string } | { type: 'code'; text: string } | { type: 'bold'; text: string };

export type MdBlock =
  | { type: 'code'; text: string }
  | { type: 'heading'; level: number; children: Inline[] }
  | { type: 'ul'; items: Inline[][] }
  | { type: 'ol'; items: Inline[][] }
  | { type: 'table'; head: Inline[][]; rows: Inline[][][] }
  | { type: 'p'; lines: Inline[][] };

export function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return String(s).replace(/\u001b\[[0-9;?]*[ -/]*[@-~]/g, '');
}

export function isMarkdown(s: string): boolean {
  return /^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|```|\|)/m.test(s);
}

export function inlineOf(line: string): Inline[] {
  const out: Inline[] = [];
  const push = (text: string, type: Inline['type']) => {
    if (text) out.push({ type, text });
  };
  const codeRe = /`([^`]+)`/g;
  let at = 0;
  const bold = (chunk: string) => {
    const re = /\*\*([^*]+)\*\*/g;
    let i = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(chunk))) {
      push(chunk.slice(i, m.index), 'text');
      push(m[1] ?? '', 'bold');
      i = m.index + m[0].length;
    }
    push(chunk.slice(i), 'text');
  };
  let m: RegExpExecArray | null;
  while ((m = codeRe.exec(line))) {
    bold(line.slice(at, m.index));
    push(m[1] ?? '', 'code');
    at = m.index + m[0].length;
  }
  bold(line.slice(at));
  return out;
}

export function parseMarkdown(src: string): MdBlock[] {
  const lines = stripAnsi(src).split('\n');
  const out: MdBlock[] = [];
  let para: string[] = [];
  let i = 0;
  const flush = () => {
    if (para.length) {
      out.push({ type: 'p', lines: para.map(inlineOf) });
      para = [];
    }
  };
  const cells = (r: string) =>
    r
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => c.trim());
  while (i < lines.length) {
    const l = lines[i]!;
    let m: RegExpExecArray | null;
    if (/^```/.test(l)) {
      flush();
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i]!)) code.push(lines[i++]!);
      i++;
      out.push({ type: 'code', text: code.join('\n') });
      continue;
    }
    if ((m = /^(#{1,6})\s+(.*)$/.exec(l))) {
      flush();
      out.push({ type: 'heading', level: (m[1] ?? '#').length, children: inlineOf(m[2] ?? '') });
      i++;
      continue;
    }
    if (/^\s*[-*]\s+/.test(l)) {
      flush();
      const items: Inline[][] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i]!)) items.push(inlineOf(lines[i++]!.replace(/^\s*[-*]\s+/, '')));
      out.push({ type: 'ul', items });
      continue;
    }
    if (/^\s*\d+\.\s+/.test(l)) {
      flush();
      const items: Inline[][] = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i]!)) items.push(inlineOf(lines[i++]!.replace(/^\s*\d+\.\s+/, '')));
      out.push({ type: 'ol', items });
      continue;
    }
    if (/^\|/.test(l) && i + 1 < lines.length && /^\|[\s:|-]+\|?$/.test(lines[i + 1]!)) {
      flush();
      const rows = [l];
      i += 2;
      while (i < lines.length && /^\|/.test(lines[i]!)) rows.push(lines[i++]!);
      out.push({ type: 'table', head: cells(rows[0]!).map(inlineOf), rows: rows.slice(1).map((r) => cells(r).map(inlineOf)) });
      continue;
    }
    if (!l.trim()) {
      flush();
      i++;
      continue;
    }
    para.push(l);
    i++;
  }
  flush();
  return out;
}

export function inlineText(spans: Inline[]): string {
  return spans.map((s) => s.text).join('');
}
