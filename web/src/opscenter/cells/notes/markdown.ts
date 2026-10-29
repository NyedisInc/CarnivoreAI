/* <script */

export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'break' }
  | { kind: 'strong'; children: Inline[] }
  | { kind: 'em'; children: Inline[] }
  | { kind: 'link'; href: string; children: Inline[] };

export type Block =
  | { kind: 'heading'; level: 1 | 2 | 3 | 4 | 5 | 6; children: Inline[] }
  | { kind: 'paragraph'; children: Inline[] }
  | { kind: 'code'; text: string }
  | { kind: 'quote'; children: Inline[] }
  | { kind: 'list'; ordered: boolean; items: Inline[][] }
  | { kind: 'rule' };

const ALLOWED_SCHEMES = /^(https?:\/\/|mailto:)/i;

const FENCE = /^\s{0,3}```/;

const HEADING = /^\s{0,3}(#{1,6})\s+(.*)$/;

const RULE = /^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$/;

const BULLET = /^\s{0,3}[-*+]\s+(.*)$/;

const NUMBERED = /^\s{0,3}\d{1,9}[.)]\s+(.*)$/;

const QUOTE = /^\s{0,3}>\s?(.*)$/;

export function allowedHref(href: string): boolean {
  return ALLOWED_SCHEMES.test(href.trim());
}

export type LinkFilter = (href: string) => boolean;

function emphasisClose(source: string, at: number, marker: string): number {
  const word = /[\p{L}\p{N}]/u;
  if (marker === '_' && at > 0 && word.test(source[at - 1] as string)) return -1;
  let close = source.indexOf(marker, at + 1);
  while (marker === '_' && close !== -1 && word.test(source[close + 1] ?? '')) {
    close = source.indexOf(marker, close + 1);
  }
  return close;
}

export function parseInline(source: string, allow: LinkFilter = allowedHref): Inline[] {
  const out: Inline[] = [];
  let buffer = '';
  let at = 0;

  const flush = (): void => {
    if (buffer) out.push({ kind: 'text', text: buffer });
    buffer = '';
  };

  while (at < source.length) {
    const char = source[at] as string;

    if (char === '\n') {
      flush();
      out.push({ kind: 'break' });
      at += 1;
      continue;
    }

    if (char === '`') {
      const close = source.indexOf('`', at + 1);
      if (close > at + 1) {
        flush();
        out.push({ kind: 'code', text: source.slice(at + 1, close) });
        at = close + 1;
        continue;
      }
    }

    if (char === '*' && source[at + 1] === '*') {
      const close = source.indexOf('**', at + 2);
      if (close > at + 2) {
        flush();
        out.push({ kind: 'strong', children: parseInline(source.slice(at + 2, close), allow) });
        at = close + 2;
        continue;
      }
    }

    if (char === '*' || char === '_') {
      const close = emphasisClose(source, at, char);
      if (close > at + 1 && source[at + 1] !== char) {
        flush();
        out.push({ kind: 'em', children: parseInline(source.slice(at + 1, close), allow) });
        at = close + 1;
        continue;
      }
    }

    if (char === '[') {
      const label = source.indexOf(']', at + 1);
      if (label > at && source[label + 1] === '(') {
        const target = source.indexOf(')', label + 2);
        if (target > label + 1) {
          const href = source.slice(label + 2, target).trim();
          if (allow(href)) {
            flush();
            out.push({
              kind: 'link',
              href,
              children: parseInline(source.slice(at + 1, label), allow),
            });
            at = target + 1;
            continue;
          }
        }
      }
    }

    buffer += char;
    at += 1;
  }

  flush();
  return out;
}

export function parseMarkdown(source: string, allow: LinkFilter = allowedHref): Block[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: Block[] = [];
  let at = 0;

  while (at < lines.length) {
    const line = lines[at] as string;

    if (!line.trim()) {
      at += 1;
      continue;
    }

    if (FENCE.test(line)) {
      const body: string[] = [];
      at += 1;
      while (at < lines.length && !FENCE.test(lines[at] as string)) {
        body.push(lines[at] as string);
        at += 1;
      }
      if (at < lines.length) at += 1;
      blocks.push({ kind: 'code', text: body.join('\n') });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const level = (heading[1] as string).length as 1 | 2 | 3 | 4 | 5 | 6;
      blocks.push({ kind: 'heading', level, children: parseInline(heading[2] as string, allow) });
      at += 1;
      continue;
    }

    if (RULE.test(line)) {
      blocks.push({ kind: 'rule' });
      at += 1;
      continue;
    }

    if (QUOTE.test(line)) {
      const body: string[] = [];
      while (at < lines.length) {
        const quoted = QUOTE.exec(lines[at] as string);
        if (!quoted) break;
        body.push(quoted[1] as string);
        at += 1;
      }
      blocks.push({ kind: 'quote', children: parseInline(body.join('\n'), allow) });
      continue;
    }

    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (bullet || numbered) {
      const ordered = bullet === null;
      const pattern = ordered ? NUMBERED : BULLET;
      const items: Inline[][] = [];
      while (at < lines.length) {
        const item = pattern.exec(lines[at] as string);
        if (!item) break;
        items.push(parseInline(item[1] as string, allow));
        at += 1;
      }
      blocks.push({ kind: 'list', ordered, items });
      continue;
    }

    const body: string[] = [];
    while (at < lines.length) {
      const next = lines[at] as string;
      if (
        !next.trim() ||
        FENCE.test(next) ||
        HEADING.test(next) ||
        RULE.test(next) ||
        QUOTE.test(next) ||
        BULLET.test(next) ||
        NUMBERED.test(next)
      ) {
        break;
      }
      body.push(next);
      at += 1;
    }
    blocks.push({ kind: 'paragraph', children: parseInline(body.join('\n'), allow) });
  }

  return blocks;
}

function buildInline(parent: Node, runs: Inline[], doc: Document, allow: LinkFilter): void {
  for (const run of runs) {
    if (run.kind === 'text') {
      parent.appendChild(doc.createTextNode(run.text));
      continue;
    }
    if (run.kind === 'break') {
      parent.appendChild(doc.createElement('br'));
      continue;
    }
    if (run.kind === 'code') {
      const code = doc.createElement('code');
      code.textContent = run.text;
      parent.appendChild(code);
      continue;
    }
    if (run.kind === 'link') {
      const link = doc.createElement('a');
      link.setAttribute('href', allow(run.href) ? run.href : '#');
      link.setAttribute('rel', 'noopener noreferrer');
      if (!run.href.startsWith('#')) link.setAttribute('target', '_blank');
      buildInline(link, run.children, doc, allow);
      parent.appendChild(link);
      continue;
    }
    const wrapper = doc.createElement(run.kind === 'strong' ? 'strong' : 'em');
    buildInline(wrapper, run.children, doc, allow);
    parent.appendChild(wrapper);
  }
}

export function renderTree(blocks: Block[], doc: Document, allow: LinkFilter = allowedHref): DocumentFragment {
  const fragment = doc.createDocumentFragment();
  for (const block of blocks) {
    if (block.kind === 'rule') {
      fragment.appendChild(doc.createElement('hr'));
      continue;
    }
    if (block.kind === 'code') {
      const pre = doc.createElement('pre');
      const code = doc.createElement('code');
      code.textContent = block.text;
      pre.appendChild(code);
      fragment.appendChild(pre);
      continue;
    }
    if (block.kind === 'list') {
      const list = doc.createElement(block.ordered ? 'ol' : 'ul');
      for (const item of block.items) {
        const entry = doc.createElement('li');
        buildInline(entry, item, doc, allow);
        list.appendChild(entry);
      }
      fragment.appendChild(list);
      continue;
    }
    const tag =
      block.kind === 'heading' ? `h${block.level}` : block.kind === 'quote' ? 'blockquote' : 'p';
    const element = doc.createElement(tag);
    buildInline(element, block.children, doc, allow);
    fragment.appendChild(element);
  }
  return fragment;
}

export function renderMarkdown(source: string, doc: Document, allow: LinkFilter = allowedHref): DocumentFragment {
  return renderTree(parseMarkdown(source, allow), doc, allow);
}
