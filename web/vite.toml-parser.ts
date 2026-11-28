
export class TomlParseError extends Error {
  readonly line: number;
  readonly column: number;
  readonly source: string;

  constructor(message: string, line: number, column: number, source: string) {
    super(`${source}:${line}:${column}: ${message}`);
    this.name = 'TomlParseError';
    this.line = line;
    this.column = column;
    this.source = source;
  }
}

type TomlTable = Record<string, unknown>;

const BARE_KEY_RE = /^[A-Za-z0-9_-]+$/;
const DEC_INT_RE = /^[+-]?(?:0|[1-9](?:_?\d)*)$/;
const HEX_INT_RE = /^0x[0-9A-Fa-f](?:_?[0-9A-Fa-f])*$/;
const OCT_INT_RE = /^0o[0-7](?:_?[0-7])*$/;
const BIN_INT_RE = /^0b[01](?:_?[01])*$/;
const FLOAT_RE = /^[+-]?(?:0|[1-9](?:_?\d)*)(?:\.\d(?:_?\d)*)?(?:[eE][+-]?\d(?:_?\d)*)?$/;
const OFFSET_DATETIME_RE = /^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$/;
const LOCAL_DATETIME_RE = /^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;
const LOCAL_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const LOCAL_TIME_RE = /^\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;

function setOwnProp(obj: TomlTable, key: string, value: unknown): void {
  Object.defineProperty(obj, key, {
    value,
    writable: true,
    enumerable: true,
    configurable: true,
  });
}

function getOwnProp(obj: TomlTable, key: string): unknown {
  return Object.hasOwn(obj, key) ? obj[key] : undefined;
}

function isPlainTable(value: unknown): value is TomlTable {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isBadControlChar(code: number, allowTab: boolean): boolean {
  if (code === 0x09) return !allowTab;
  return (code >= 0x00 && code <= 0x08) || (code >= 0x0a && code <= 0x1f) || code === 0x7f;
}

class TomlScanner {
  private readonly src: string;
  private readonly file: string;
  private pos = 0;
  private line = 1;
  private col = 1;

  private readonly explicitTables = new WeakSet<TomlTable>();
  private readonly dottedTables = new WeakSet<TomlTable>();
  private readonly inlineTables = new WeakSet<TomlTable>();
  private readonly aotArrays = new WeakSet<unknown[]>();

  constructor(raw: string, file: string) {
    const withoutBom = raw.startsWith('\uFEFF') ? raw.slice(1) : raw;
    this.src = withoutBom.replace(/\r\n/g, '\n');
    this.file = file;
  }

  private fail(msg: string): never {
    throw new TomlParseError(msg, this.line, this.col, this.file);
  }

  private eof(): boolean {
    return this.pos >= this.src.length;
  }

  private peek(offset = 0): string {
    return this.src[this.pos + offset] ?? '';
  }

  private advance(): string {
    const ch = this.src[this.pos] ?? '';
    this.pos += 1;
    if (ch === '\n') {
      this.line += 1;
      this.col = 1;
    } else {
      this.col += 1;
    }
    return ch;
  }

  private skipHorizontalWs(): void {
    while (!this.eof()) {
      const ch = this.peek();
      if (ch === ' ' || ch === '\t') this.advance();
      else break;
    }
  }

  private skipCommentIfPresent(): void {
    if (this.peek() !== '#') return;
    this.advance();
    while (!this.eof()) {
      const ch = this.peek();
      if (ch === '\n') break;
      const code = ch.charCodeAt(0);
      if (isBadControlChar(code, true)) {
        this.fail('invalid control character in comment');
      }
      this.advance();
    }
  }

  private skipWsAndNewlinesAndComments(): void {
    while (!this.eof()) {
      const ch = this.peek();
      if (ch === ' ' || ch === '\t' || ch === '\n') {
        this.advance();
      } else if (ch === '#') {
        this.skipCommentIfPresent();
      } else {
        break;
      }
    }
  }

  private expectLineEnd(): void {
    this.skipHorizontalWs();
    this.skipCommentIfPresent();
    if (this.eof()) return;
    if (this.peek() === '\n') {
      this.advance();
      return;
    }
    this.fail(`unexpected character ${JSON.stringify(this.peek())}`);
  }

  private parseUnicodeEscape(digits: number): string {
    let hex = '';
    for (let i = 0; i < digits; i += 1) {
      const ch = this.advance();
      if (!/[0-9a-fA-F]/.test(ch)) this.fail(`invalid unicode escape character ${JSON.stringify(ch)}`);
      hex += ch;
    }
    const code = Number.parseInt(hex, 16);
    if (code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) {
      this.fail(`invalid unicode scalar value U+${hex.toUpperCase()}`);
    }
    return String.fromCodePoint(code);
  }

  private parseBasicString(multiline: boolean): string {
    if (multiline) {
      this.advance();
      this.advance();
      this.advance();
      if (this.peek() === '\n') this.advance();
    } else {
      this.advance();
    }

    let out = '';
    while (!this.eof()) {
      const ch = this.peek();
      if (multiline && ch === '"' && this.peek(1) === '"' && this.peek(2) === '"') {
        this.advance();
        this.advance();
        this.advance();
        let extra = 0;
        while (this.peek() === '"' && extra < 2) {
          this.advance();
          out += '"';
          extra += 1;
        }
        if (this.peek() === '"') this.fail('too many consecutive quotes closing multiline basic string');
        return out;
      }
      if (!multiline && ch === '"') {
        this.advance();
        return out;
      }
      if (!multiline && ch === '\n') {
        this.fail('unterminated basic string');
      }
      if (ch === '\\') {
        this.advance();
        if (this.eof()) this.fail('unterminated escape sequence');
        const esc = this.advance();
        if (esc === 'b') out += '\b';
        else if (esc === 't') out += '\t';
        else if (esc === 'n') out += '\n';
        else if (esc === 'f') out += '\f';
        else if (esc === 'r') out += '\r';
        else if (esc === '"') out += '"';
        else if (esc === '\\') out += '\\';
        else if (esc === 'u') out += this.parseUnicodeEscape(4);
        else if (esc === 'U') out += this.parseUnicodeEscape(8);
        else if (multiline && (esc === ' ' || esc === '\t' || esc === '\n')) {
          if (esc !== '\n') {
            this.skipHorizontalWs();
            if (this.peek() !== '\n') this.fail('invalid line-ending backslash in multiline string');
            this.advance();
          }
          while (!this.eof()) {
            const ws = this.peek();
            if (ws === ' ' || ws === '\t' || ws === '\n') this.advance();
            else break;
          }
        } else {
          this.fail(`invalid escape sequence \\${esc}`);
        }
        continue;
      }
      const code = ch.charCodeAt(0);
      if (multiline && ch === '\n') {
        out += this.advance();
        continue;
      }
      if (isBadControlChar(code, true)) {
        this.fail('invalid control character in string');
      }
      out += this.advance();
    }
    this.fail('unterminated string');
  }

  private parseLiteralString(multiline: boolean): string {
    if (multiline) {
      this.advance();
      this.advance();
      this.advance();
      if (this.peek() === '\n') this.advance();
    } else {
      this.advance();
    }

    let out = '';
    while (!this.eof()) {
      const ch = this.peek();
      if (multiline && ch === '\'' && this.peek(1) === '\'' && this.peek(2) === '\'') {
        this.advance();
        this.advance();
        this.advance();
        let extra = 0;
        while (this.peek() === '\'' && extra < 2) {
          this.advance();
          out += '\'';
          extra += 1;
        }
        if (this.peek() === '\'') this.fail('too many consecutive quotes closing multiline literal string');
        return out;
      }
      if (!multiline && ch === '\'') {
        this.advance();
        return out;
      }
      if (!multiline && ch === '\n') {
        this.fail('unterminated literal string');
      }
      if (multiline && ch === '\n') {
        out += this.advance();
        continue;
      }
      const code = ch.charCodeAt(0);
      if (isBadControlChar(code, true)) {
        this.fail('invalid control character in literal string');
      }
      out += this.advance();
    }
    this.fail('unterminated literal string');
  }

  private parseKeyPart(): string {
    this.skipHorizontalWs();
    const ch = this.peek();
    if (ch === '"') {
      if (this.peek(1) === '"' && this.peek(2) === '"') this.fail('multiline strings are not allowed as keys');
      return this.parseBasicString(false);
    }
    if (ch === '\'') {
      if (this.peek(1) === '\'' && this.peek(2) === '\'') this.fail('multiline strings are not allowed as keys');
      return this.parseLiteralString(false);
    }
    let raw = '';
    while (!this.eof()) {
      const c = this.peek();
      if (/[A-Za-z0-9_-]/.test(c)) raw += this.advance();
      else break;
    }
    if (!raw || !BARE_KEY_RE.test(raw)) {
      this.fail(`expected key, got ${JSON.stringify(ch || 'EOF')}`);
    }
    return raw;
  }

  private parseKeyPath(): string[] {
    const parts: string[] = [this.parseKeyPart()];
    while (true) {
      this.skipHorizontalWs();
      if (this.peek() !== '.') break;
      this.advance();
      parts.push(this.parseKeyPart());
    }
    return parts;
  }

  private resolveHeaderPath(root: TomlTable, path: string[], isArrayOfTables: boolean): TomlTable {
    let curr: TomlTable = root;
    const lastIdx = path.length - 1;
    for (let i = 0; i < lastIdx; i += 1) {
      const key = path[i]!;
      const existing = getOwnProp(curr, key);
      if (existing === undefined) {
        const next: TomlTable = {};
        setOwnProp(curr, key, next);
        curr = next;
      } else if (Array.isArray(existing) && this.aotArrays.has(existing)) {
        const tail = existing[existing.length - 1];
        if (!isPlainTable(tail)) this.fail(`invalid array-of-tables element at ${key}`);
        curr = tail;
      } else if (isPlainTable(existing)) {
        if (this.inlineTables.has(existing)) {
          this.fail(`cannot reopen inline table ${key}`);
        }
        curr = existing;
      } else {
        this.fail(`key ${key} is already defined as a non-table value`);
      }
    }

    const leaf = path[lastIdx]!;
    const existing = getOwnProp(curr, leaf);
    if (isArrayOfTables) {
      if (existing === undefined) {
        const arr: TomlTable[] = [];
        this.aotArrays.add(arr);
        setOwnProp(curr, leaf, arr);
        const item: TomlTable = {};
        this.explicitTables.add(item);
        arr.push(item);
        return item;
      }
      if (!Array.isArray(existing) || !this.aotArrays.has(existing)) {
        this.fail(`cannot append [[${path.join('.')}]] to non-array-of-tables key`);
      }
      const item: TomlTable = {};
      this.explicitTables.add(item);
      existing.push(item);
      return item;
    }

    if (existing === undefined) {
      const tbl: TomlTable = {};
      this.explicitTables.add(tbl);
      setOwnProp(curr, leaf, tbl);
      return tbl;
    }
    if (!isPlainTable(existing)) {
      this.fail(`cannot redefine non-table key ${path.join('.')} as a table`);
    }
    if (this.explicitTables.has(existing) || this.dottedTables.has(existing) || this.inlineTables.has(existing)) {
      this.fail(`table [${path.join('.')}] cannot be redefined`);
    }
    this.explicitTables.add(existing);
    return existing;
  }

  private setDottedValue(target: TomlTable, path: string[], value: unknown): void {
    let curr = target;
    const lastIdx = path.length - 1;
    for (let i = 0; i < lastIdx; i += 1) {
      const key = path[i]!;
      const existing = getOwnProp(curr, key);
      if (existing === undefined) {
        const next: TomlTable = {};
        this.dottedTables.add(next);
        setOwnProp(curr, key, next);
        curr = next;
      } else if (isPlainTable(existing)) {
        if (this.inlineTables.has(existing)) {
          this.fail(`cannot extend inline table via dotted key ${path.join('.')}`);
        }
        if (this.explicitTables.has(existing)) {
          this.fail(`cannot extend explicitly declared table [${key}] via dotted key`);
        }
        this.dottedTables.add(existing);
        curr = existing;
      } else {
        this.fail(`key ${key} is already defined as a non-table value`);
      }
    }

    const leaf = path[lastIdx]!;
    if (Object.hasOwn(curr, leaf)) {
      this.fail(`duplicate key ${path.join('.')}`);
    }
    setOwnProp(curr, leaf, value);
  }

  private parseArray(): unknown[] {
    this.advance();
    const items: unknown[] = [];
    while (true) {
      this.skipWsAndNewlinesAndComments();
      if (this.eof()) this.fail('unterminated array');
      if (this.peek() === ']') {
        this.advance();
        return items;
      }
      items.push(this.parseValue());
      this.skipWsAndNewlinesAndComments();
      const next = this.peek();
      if (next === ',') {
        this.advance();
        continue;
      }
      if (next === ']') {
        this.advance();
        return items;
      }
      this.fail(`expected ',' or ']' in array, got ${JSON.stringify(next || 'EOF')}`);
    }
  }

  private parseInlineTable(): TomlTable {
    this.advance();
    const tbl: TomlTable = {};
    this.skipHorizontalWs();
    if (this.peek() === '}') {
      this.advance();
      this.inlineTables.add(tbl);
      return tbl;
    }
    while (true) {
      this.skipHorizontalWs();
      if (this.eof() || this.peek() === '\n') this.fail('unterminated inline table');
      const path = this.parseKeyPath();
      this.skipHorizontalWs();
      if (this.peek() !== '=') this.fail("expected '=' after key in inline table");
      this.advance();
      this.skipHorizontalWs();
      const val = this.parseValue();
      this.setDottedValue(tbl, path, val);
      this.skipHorizontalWs();
      const ch = this.peek();
      if (ch === '}') {
        this.advance();
        this.inlineTables.add(tbl);
        return tbl;
      }
      if (ch === ',') {
        this.advance();
        this.skipHorizontalWs();
        if (this.peek() === '}') this.fail('trailing comma is not allowed in inline table');
        continue;
      }
      this.fail(`expected ',' or '}' in inline table, got ${JSON.stringify(ch || 'EOF')}`);
    }
  }

  private parseScalarToken(): unknown {
    let token = '';
    while (!this.eof()) {
      const ch = this.peek();
      if (ch === '#' || ch === '\n' || ch === ',' || ch === ']' || ch === '}') break;
      if (ch === ' ' || ch === '\t') {
        if (LOCAL_DATE_RE.test(token) && /^\d{2}:\d{2}:\d{2}/.test(this.src.slice(this.pos + 1))) {
          token += this.advance();
          continue;
        }
        break;
      }
      token += this.advance();
    }

    if (!token) this.fail('expected value');
    if (token === 'true') return true;
    if (token === 'false') return false;
    if (token === 'inf' || token === '+inf') return Number.POSITIVE_INFINITY;
    if (token === '-inf') return Number.NEGATIVE_INFINITY;
    if (token === 'nan' || token === '+nan' || token === '-nan') return Number.NaN;

    if (HEX_INT_RE.test(token)) return Number.parseInt(token.slice(2).replace(/_/g, ''), 16);
    if (OCT_INT_RE.test(token)) return Number.parseInt(token.slice(2).replace(/_/g, ''), 8);
    if (BIN_INT_RE.test(token)) return Number.parseInt(token.slice(2).replace(/_/g, ''), 2);
    if (DEC_INT_RE.test(token)) return Number.parseInt(token.replace(/_/g, ''), 10);

    if (token.includes('.') || token.includes('e') || token.includes('E')) {
      if (FLOAT_RE.test(token)) {
        const parsed = Number.parseFloat(token.replace(/_/g, ''));
        if (!Number.isNaN(parsed)) return parsed;
      }
    }

    if (
      OFFSET_DATETIME_RE.test(token)
      || LOCAL_DATETIME_RE.test(token)
      || LOCAL_DATE_RE.test(token)
      || LOCAL_TIME_RE.test(token)
    ) {
      return token;
    }

    this.fail(`invalid value ${JSON.stringify(token)}`);
  }

  private parseValue(): unknown {
    this.skipHorizontalWs();
    if (this.eof()) this.fail('expected value, reached EOF');
    const ch = this.peek();
    if (ch === '"') {
      return this.parseBasicString(this.peek(1) === '"' && this.peek(2) === '"');
    }
    if (ch === '\'') {
      return this.parseLiteralString(this.peek(1) === '\'' && this.peek(2) === '\'');
    }
    if (ch === '[') return this.parseArray();
    if (ch === '{') return this.parseInlineTable();
    return this.parseScalarToken();
  }

  parse(): TomlTable {
    const root: TomlTable = {};
    let currentTable: TomlTable = root;

    while (!this.eof()) {
      this.skipWsAndNewlinesAndComments();
      if (this.eof()) break;

      if (this.peek() === '[') {
        this.advance();
        const isAot = this.peek() === '[';
        if (isAot) this.advance();
        const path = this.parseKeyPath();
        this.skipHorizontalWs();
        if (this.peek() !== ']') this.fail("expected ']' closing table header");
        this.advance();
        if (isAot) {
          if (this.peek() !== ']') this.fail("expected ']]' closing array-of-tables header");
          this.advance();
        }
        this.expectLineEnd();
        currentTable = this.resolveHeaderPath(root, path, isAot);
        continue;
      }

      const path = this.parseKeyPath();
      this.skipHorizontalWs();
      if (this.peek() !== '=') this.fail("expected '=' after key");
      this.advance();
      const val = this.parseValue();
      this.expectLineEnd();
      this.setDottedValue(currentTable, path, val);
    }

    return root;
  }
}

export function parseToml(source: string, filename = '<toml>'): TomlTable {
  return new TomlScanner(source, filename).parse();
}
