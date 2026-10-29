
export const MAX_NODES = 500;
export const MAX_DEPTH = 12;
export const MAX_BYTES = 64 * 1024;
export const MAX_ROWS = 100;
export const MAX_COLUMNS = 12;
export const MAX_TEXT = 2000;
export const MAX_LABEL = 200;
export const MAX_PAYLOAD_BYTES = 4096;
export const SCHEMA = 1;

export const TONES: ReadonlySet<string> = new Set(['normal', 'muted', 'accent', 'warn', 'danger']);
export const STATUSES: ReadonlySet<string> = new Set(['working', 'working_subagent', 'question', 'notice', 'finished_unread', 'idle', 'dead', 'unknown']);

export const NODE_FIELDS: Readonly<Record<string, readonly string[]>> = {
    section: ['title', 'children'],
    row: ['children', 'gap', 'wrap'],
    column: ['children', 'gap', 'wrap'],
    text: ['value', 'tone'],
    badge: ['status', 'text', 'tone'],
    stat: ['label', 'value', 'unit', 'delta', 'tone'],
    list: ['items', 'empty'],
    table: ['columns', 'rows'],
    button: ['label', 'action', 'confirm', 'tone'],
    meter: ['value', 'max', 'label', 'thresholds'],
};

export type Scalar = string | number | boolean | null | { bind: string };
export type Tone = 'normal' | 'muted' | 'accent' | 'warn' | 'danger';
export type Action =
    | { call: 'route'; route: string; payload?: Record<string, unknown> }
    | { call: 'tool'; name: string; payload?: Record<string, unknown> };

export type UiNode =
    | { type: 'section'; title?: string; children: UiNode[] }
    | { type: 'row' | 'column'; children: UiNode[]; gap?: number; wrap?: boolean }
    | { type: 'text'; value: Scalar; tone?: Tone }
    | { type: 'badge'; status?: string; text?: string; tone?: Tone }
    | { type: 'stat'; label: string; value: Scalar; unit?: string; delta?: string; tone?: Tone }
    | { type: 'list'; items: UiNode[]; empty?: string }
    | { type: 'table'; columns: string[]; rows: Scalar[][] }
    | { type: 'button'; label: string; action: Action; confirm?: string; tone?: Tone }
    | { type: 'meter'; label: string; value: Scalar; max: Scalar; thresholds?: number[] };

export interface UiDocument {
    schema: 1;
    root: UiNode;
    data?: Record<string, unknown>;
}

export interface Declared {
    readonly routes: readonly string[];
    readonly tools: readonly string[];
}

export type Verdict = { ok: true; doc: UiDocument } | { ok: false; code: string; path: string };

class Refuse extends Error {
    constructor(readonly code: string, readonly path: string) {
        super(code);
    }
}

const INVISIBLE = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}\p{Zl}\p{Zp}]/u;
const SCHEME = /(^|[\s(<[\"'])[a-z][a-z0-9+.\-]{1,20}:(\/\/|[^\s0-9])/i;
const DATA_ID = /^(adopted|plugin|remote):[A-Za-z0-9_.:-]{1,200}$/;
const POINTER = /^(\/[A-Za-z0-9_-]{1,40}){1,8}$/;
const SECRET_SHAPES: readonly RegExp[] = [
    /(?<!\w)gh[pousr]_[A-Za-z0-9]{30,}/,
    /(?<!\w)github_pat_[A-Za-z0-9_]{20,}/,
    /(?<!\w)(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])/,
    /(?<!\w)AIza[0-9A-Za-z_-]{35}\b/,
    /(?<!\w)xox[abprs]-[A-Za-z0-9-]{10,}/,
    /(?<!\w)xapp-[A-Za-z0-9-]{10,}/,
    /(?<!\w)[rs]k_(?:live|test)_[A-Za-z0-9]{24,99}/,
    /(?<!\w)sk-[A-Za-z0-9_-]{20,}/,
    /(?<!\w)hf_[A-Za-z0-9]{30,40}(?![A-Za-z0-9])/,
    /(?<!\w)npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])/,
    /(?<!\w)glpat-[A-Za-z0-9_-]{20,50}/,
    /(?<!\w)(?:cbt|cak)_[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])/,
    /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
    /(?<!\w)Bearer\s+[A-Za-z0-9._~+/-]{20,}/i,
    /(?<!\w)eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/,
];

function size(value: string): number {
    let n = 0;
    for (const _c of value) n += 1;
    return n;
}

function asciiEscaped(text: string): string {
    return text.replace(/[\u007f-\uffff]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

function pyDump(value: unknown): string {
    if (value === null) return 'null';
    if (Array.isArray(value)) return `[${value.map((v) => pyDump(v === undefined ? null : v)).join(', ')}]`;
    if (typeof value === 'object') {
        const parts = Object.entries(value as Record<string, unknown>)
            .filter(([, v]) => v !== undefined && typeof v !== 'function')
            .map(([k, v]) => `${asciiEscaped(JSON.stringify(k))}: ${pyDump(v)}`);
        return `{${parts.join(', ')}}`;
    }
    if (typeof value === 'string') return asciiEscaped(JSON.stringify(value));
    if (typeof value === 'number') {
        if (!Number.isFinite(value)) throw new Refuse('not_json', '');
        return JSON.stringify(value);
    }
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    throw new Refuse('not_json', '');
}

export function jsonSize(value: unknown): number {
    return pyDump(value).length;
}

function isObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

class Walk {
    nodes = 0;
    readonly routes: ReadonlySet<string>;
    readonly tools: ReadonlySet<string>;

    constructor(declared: Declared) {
        this.routes = new Set(declared.routes);
        this.tools = new Set(declared.tools);
    }

    string(value: unknown, path: string, limit: number, scheme = true): string {
        if (typeof value !== 'string' || size(value) > limit) throw new Refuse('bad_string', path);
        if (INVISIBLE.test(value)) throw new Refuse('invisible_character', path);
        if (SCHEME.test(value) && (scheme || !DATA_ID.test(value))) throw new Refuse('link_not_allowed', path);
        if (SECRET_SHAPES.some((re) => re.test(value))) throw new Refuse('secret_shape', path);
        return value;
    }

    scalar(value: unknown, path: string, limit: number = MAX_TEXT): Scalar {
        if (value === null || typeof value === 'boolean') return value;
        if (typeof value === 'number') {
            if (!Number.isFinite(value)) throw new Refuse('bad_number', path);
            return value;
        }
        if (isObject(value)) {
            const keys = Object.keys(value);
            if (keys.length !== 1 || keys[0] !== 'bind' || typeof value.bind !== 'string' || !POINTER.test(value.bind)) throw new Refuse('bad_bind', path);
            return { bind: value.bind };
        }
        return this.string(value, path, limit);
    }

    tone(raw: Record<string, unknown>, path: string): { tone?: Tone } {
        if (!('tone' in raw)) return {};
        if (typeof raw.tone !== 'string' || !TONES.has(raw.tone)) throw new Refuse('bad_tone', `${path}/tone`);
        return { tone: raw.tone as Tone };
    }

    action(raw: unknown, path: string): Action {
        if (!isObject(raw)) throw new Refuse('bad_action', path);
        const call = raw.call;
        if (call !== 'route' && call !== 'tool') throw new Refuse('action_not_supported', `${path}/call`);
        const field = call === 'route' ? 'route' : 'name';
        const declared = call === 'route' ? this.routes : this.tools;
        const extra = Object.keys(raw).some((k) => k !== 'call' && k !== field && k !== 'payload');
        const named = raw[field];
        if (extra || typeof named !== 'string' || !declared.has(named)) throw new Refuse('action_not_declared', `${path}/${field}`);
        const out: Action = call === 'route' ? { call, route: named } : { call, name: named };
        if ('payload' in raw) {
            if (!isObject(raw.payload) || jsonSize(raw.payload) > MAX_PAYLOAD_BYTES) throw new Refuse('bad_payload', `${path}/payload`);
            out.payload = this.json(raw.payload, `${path}/payload`, 0) as Record<string, unknown>;
        }
        return out;
    }

    json(value: unknown, path: string, depth: number, scheme = true): unknown {
        if (depth > 6) throw new Refuse('too_deep', path);
        if (Array.isArray(value)) return value.slice(0, 100).map((v, i) => this.json(v, `${path}/${i}`, depth + 1, scheme));
        if (isObject(value)) {
            const out: Record<string, unknown> = {};
            for (const [k, v] of Object.entries(value)) out[this.string(k, path, MAX_LABEL, scheme)] = this.json(v, `${path}/${k.slice(0, 20)}`, depth + 1, scheme);
            return out;
        }
        if (typeof value === 'string') return this.string(value, path, MAX_TEXT, scheme);
        if (value === null || typeof value === 'boolean' || typeof value === 'number') return this.scalar(value, path);
        throw new Refuse('bad_value', path);
    }

    kids(raw: Record<string, unknown>, key: string, path: string, depth: number): UiNode[] {
        const items = key in raw ? raw[key] : [];
        if (!Array.isArray(items)) throw new Refuse('bad_children', `${path}/${key}`);
        return items.map((c, i) => this.node(c, `${path}/${key}/${i}`, depth + 1));
    }

    node(raw: unknown, path: string, depth: number): UiNode {
        if (depth > MAX_DEPTH) throw new Refuse('too_deep', path);
        this.nodes += 1;
        if (this.nodes > MAX_NODES) throw new Refuse('too_many_nodes', path);
        if (!isObject(raw)) throw new Refuse('bad_node', path);
        const kind = raw.type;
        if (typeof kind !== 'string' || !Object.hasOwn(NODE_FIELDS, kind)) throw new Refuse('unknown_node', `${path}/type`);
        const allowed = new Set([...NODE_FIELDS[kind]!, 'type']);
        const extra = Object.keys(raw).filter((k) => !allowed.has(k)).sort()[0];
        if (extra !== undefined) throw new Refuse('unknown_field', `${path}/${extra.slice(0, 30)}`);
        return { type: kind, ...this.body(kind, raw, path, depth) } as UiNode;
    }

    body(kind: string, raw: Record<string, unknown>, path: string, depth: number): Record<string, unknown> {
        switch (kind) {
            case 'section': {
                const out: Record<string, unknown> = { children: this.kids(raw, 'children', path, depth) };
                if ('title' in raw) out.title = this.string(raw.title, `${path}/title`, MAX_LABEL);
                return out;
            }
            case 'row':
            case 'column': {
                const out: Record<string, unknown> = { children: this.kids(raw, 'children', path, depth) };
                if ('gap' in raw) {
                    if (typeof raw.gap !== 'number' || !Number.isInteger(raw.gap) || raw.gap < 0 || raw.gap > 8) throw new Refuse('bad_gap', `${path}/gap`);
                    out.gap = raw.gap;
                }
                if ('wrap' in raw) {
                    if (typeof raw.wrap !== 'boolean') throw new Refuse('bad_wrap', `${path}/wrap`);
                    out.wrap = raw.wrap;
                }
                return out;
            }
            case 'text':
                if (!('value' in raw)) throw new Refuse('missing_value', path);
                return { value: this.scalar(raw.value, `${path}/value`), ...this.tone(raw, path) };
            case 'badge': {
                if (('status' in raw) === ('text' in raw)) throw new Refuse('badge_needs_status_or_text', path);
                const out: Record<string, unknown> = this.tone(raw, path);
                if ('status' in raw) {
                    if (typeof raw.status !== 'string' || !STATUSES.has(raw.status)) throw new Refuse('bad_status', `${path}/status`);
                    out.status = raw.status;
                } else out.text = this.string(raw.text, `${path}/text`, MAX_LABEL);
                return out;
            }
            case 'stat': {
                if (!('value' in raw) || !('label' in raw)) throw new Refuse('missing_value', path);
                const out: Record<string, unknown> = {
                    label: this.string(raw.label, `${path}/label`, MAX_LABEL),
                    value: this.scalar(raw.value, `${path}/value`, MAX_LABEL),
                    ...this.tone(raw, path),
                };
                for (const key of ['unit', 'delta']) if (key in raw) out[key] = this.string(raw[key], `${path}/${key}`, MAX_LABEL);
                return out;
            }
            case 'list': {
                const out: Record<string, unknown> = { items: this.kids(raw, 'items', path, depth) };
                if ('empty' in raw) out.empty = this.string(raw.empty, `${path}/empty`, MAX_LABEL);
                return out;
            }
            case 'table': {
                const cols = raw.columns;
                const rows = 'rows' in raw ? raw.rows : [];
                if (!Array.isArray(cols) || cols.length < 1 || cols.length > MAX_COLUMNS || !Array.isArray(rows)) throw new Refuse('bad_table', path);
                if (rows.length > MAX_ROWS) throw new Refuse('too_many_rows', `${path}/rows`);
                const outRows = rows.map((row, i) => {
                    if (!Array.isArray(row) || row.length !== cols.length) throw new Refuse('bad_row', `${path}/rows/${i}`);
                    return row.map((cell, j) => this.scalar(cell, `${path}/rows/${i}/${j}`, MAX_LABEL));
                });
                return { columns: cols.map((c, j) => this.string(c, `${path}/columns/${j}`, MAX_LABEL)), rows: outRows };
            }
            case 'button': {
                if (!('label' in raw) || !('action' in raw)) throw new Refuse('missing_value', path);
                const out: Record<string, unknown> = {
                    label: this.string(raw.label, `${path}/label`, MAX_LABEL),
                    action: this.action(raw.action, `${path}/action`),
                    ...this.tone(raw, path),
                };
                if ('confirm' in raw) out.confirm = this.string(raw.confirm, `${path}/confirm`, MAX_LABEL);
                return out;
            }
            default: {
                if (!['value', 'max', 'label'].every((k) => k in raw)) throw new Refuse('missing_value', path);
                const out: Record<string, unknown> = {
                    label: this.string(raw.label, `${path}/label`, MAX_LABEL),
                    value: this.scalar(raw.value, `${path}/value`),
                    max: this.scalar(raw.max, `${path}/max`),
                };
                if ('thresholds' in raw) {
                    const t = raw.thresholds;
                    if (!Array.isArray(t) || t.length > 8 || t.some((x) => typeof x !== 'number')) throw new Refuse('bad_thresholds', `${path}/thresholds`);
                    out.thresholds = t;
                }
                return out;
            }
        }
    }
}

export function validateDocument(document: unknown, declared: Declared): Verdict {
    try {
        if (!isObject(document) || Object.keys(document).some((k) => k !== 'schema' && k !== 'root' && k !== 'data')) throw new Refuse('bad_document', '');
        if (document.schema !== SCHEMA) throw new Refuse('bad_schema', '/schema');
        if (jsonSize(document) > MAX_BYTES) throw new Refuse('too_large', '');
        const walk = new Walk(declared);
        const doc: UiDocument = { schema: SCHEMA, root: walk.node(document.root, '/root', 0) };
        if ('data' in document) {
            if (!isObject(document.data)) throw new Refuse('bad_data', '/data');
            doc.data = walk.json(document.data, '/data', 0, false) as Record<string, unknown>;
        }
        return { ok: true, doc };
    } catch (error) {
        if (error instanceof Refuse) return { ok: false, code: error.code, path: error.path };
        return { ok: false, code: 'bad_document', path: '' };
    }
}

export function resolve(value: Scalar, data: Record<string, unknown> | undefined): string | number | boolean {
    if (value === null) return '';
    if (typeof value !== 'object') return value;
    let at: unknown = data;
    for (const part of value.bind.split('/').slice(1)) at = isObject(at) ? at[part] : undefined;
    return typeof at === 'string' || typeof at === 'number' || typeof at === 'boolean' ? at : '';
}
