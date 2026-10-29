
export interface CellSource {
  path: string;
  text: string;
}

export type MenuRule = 'body-menu-button' | 'menu-without-declared-actions';

export interface MenuFinding {
  rule: MenuRule;
  path: string;
  line: number;
  detail: string;
}

export const MENU_COMPONENTS = ['CascadeMenu', 'PointerMenu'] as const;

const KEBAB = /name=["'](?:kebab|dots|more|ellipsis|more-vertical|more-horizontal)["']/;
const KEBAB_TEXT = />\s*[\u22ee\u22ef]\s*</;
const HASPOPUP_MENU = /aria-haspopup=["']menu["']/;

interface Tag {
  text: string;
  line: number;
}

export function readMarkup(text: string): Tag[] {
  const tags: Tag[] = [];
  let line = 1;
  let i = 0;
  const skipTo = (end: string): void => {
    const at = text.indexOf(end, i);
    const stop = at < 0 ? text.length : at + end.length;
    for (let k = i; k < stop; k++) if (text[k] === '\n') line++;
    i = stop;
  };
  while (i < text.length) {
    const ch = text[i];
    if (ch === '\n') { line++; i++; continue; }
    if (text.startsWith('<!--', i)) { skipTo('-->'); continue; }
    if (/^<script[\s>]/.test(text.slice(i, i + 8))) { skipTo('</script>'); continue; }
    if (/^<style[\s>]/.test(text.slice(i, i + 7))) { skipTo('</style>'); continue; }
    if (ch === '<' && /[A-Za-z]/.test(text[i + 1] ?? '')) {
      const startLine = line;
      let depth = 0;
      let quote: string | null = null;
      let k = i + 1;
      for (; k < text.length; k++) {
        const c = text[k];
        if (c === '\n') line++;
        if (quote) { if (c === quote && text[k - 1] !== '\\') quote = null; continue; }
        if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
        if (c === '{') depth++;
        else if (c === '}') depth--;
        else if (c === '>' && depth <= 0) break;
      }
      tags.push({ text: text.slice(i, k + 1), line: startLine });
      i = k + 1;
      continue;
    }
    i++;
  }
  return tags;
}

export function scanCell(sources: readonly CellSource[]): MenuFinding[] {
  const found: MenuFinding[] = [];
  const declares = sources.some((one) => /\bdeclareWidgetActions\s*\(/.test(one.text));
  for (const source of sources) {
    if (!source.path.endsWith('.svelte')) continue;
    const tags = readMarkup(source.text);
    const menuImport = MENU_COMPONENTS.find((name) => new RegExp(`import\\s+${name}\\b|\\b${name}\\s*[,}].*from`).test(source.text));
    if (menuImport && !declares) {
      const at = source.text.split('\n').findIndex((row) => row.includes(menuImport));
      found.push({ rule: 'menu-without-declared-actions', path: source.path, line: at + 1,
        detail: `draws ${menuImport} but the cell never calls declareWidgetActions, so the one widget menu does not offer what it does` });
    }
    {
      for (const tag of tags) {
        if (HASPOPUP_MENU.test(tag.text) || KEBAB.test(tag.text)) {
          found.push({ rule: 'body-menu-button', path: source.path, line: tag.line,
            detail: 'a menu button in the widget; its items belong in the one widget menu (declareWidgetActions)' });
        }
      }
    }
    {
      const glyph = source.text.split('\n').findIndex((row) => KEBAB_TEXT.test(row));
      if (glyph >= 0) {
        found.push({ rule: 'body-menu-button', path: source.path, line: glyph + 1, detail: 'a kebab glyph in the widget; its items belong in the one widget menu' });
      }
    }
  }
  return found;
}

export type DataRule = 'data-fetch' | 'data-interval';

export interface DataFinding {
  rule: DataRule;
  path: string;
  line: number;
  detail: string;
}

const DATA_CALL = /(?<![\w$])(?<!(?<!window|globalThis)\.)(authFetch|fetch|setInterval)\s*\(/g;

export function codeOnly(text: string): string {
  let out = '';
  let i = 0;
  const blank = (chunk: string): string => chunk.replace(/[^\n]/g, ' ');
  while (i < text.length) {
    const two = text.slice(i, i + 2);
    if (two === '//') {
      const end = text.indexOf('\n', i);
      const stop = end < 0 ? text.length : end;
      out += blank(text.slice(i, stop));
      i = stop;
    } else if (two === '/*') {
      const end = text.indexOf('*/', i + 2);
      const stop = end < 0 ? text.length : end + 2;
      out += blank(text.slice(i, stop));
      i = stop;
    } else if (text[i] === '"' || text[i] === "'" || text[i] === '`') {
      const quote = text[i]!;
      let k = i + 1;
      while (k < text.length && text[k] !== quote && !(quote !== '`' && text[k] === '\n')) k += text[k] === '\\' ? 2 : 1;
      out += quote + blank(text.slice(i + 1, k)) + (text[k] === quote ? quote : '');
      i = k + 1;
    } else {
      out += text[i];
      i++;
    }
  }
  return out;
}

function scriptText(text: string): string {
  let out = text.replace(/[^\n]/g, ' ');
  for (const m of text.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) {
    const at = m.index! + m[0].indexOf('>') + 1;
    out = out.slice(0, at) + m[1] + out.slice(at + m[1]!.length);
  }
  return out;
}

export function scanCellData(sources: readonly CellSource[]): DataFinding[] {
  const found: DataFinding[] = [];
  for (const source of sources) {
    if (!/\.(svelte|ts)$/.test(source.path)) continue;
    const code = codeOnly(source.path.endsWith('.svelte') ? scriptText(source.text) : source.text);
    for (const m of code.matchAll(DATA_CALL)) {
      const line = code.slice(0, m.index).split('\n').length;
      const interval = m[1] === 'setInterval';
      found.push({ rule: interval ? 'data-interval' : 'data-fetch', path: source.path, line,
        detail: interval ? 'a timer of its own; a cell reads a shared store that refreshes once for all (widget-spec section 14)'
          : `${m[1]}( in the cell; a cell reads a shared store, it never fetches (widget-spec section 14)` });
    }
  }
  return found;
}
