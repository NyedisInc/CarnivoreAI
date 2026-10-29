import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '__goldens__');

export const UPDATING = typeof process !== 'undefined' && process.env.DIALOG_GOLDENS === 'update';

const SCOPE_CLASS = /^svelte-[a-z0-9]+$/;

function attrsOf(el: Element): string {
  const out: string[] = [];
  for (const attr of [...el.attributes].sort((a, b) => a.name.localeCompare(b.name))) {
    let value = attr.value;
    if (attr.name === 'class') {
      value = value.split(/\s+/).filter((one) => one && !SCOPE_CLASS.test(one)).sort().join(' ');
      if (!value) continue;
    }
    if (attr.name === 'style') value = value.replace(/\s+/g, ' ').trim();
    out.push(` ${attr.name}="${value}"`);
  }
  return out.join('');
}

export function snapshot(node: Node, depth = 0): string {
  const pad = '  '.repeat(depth);
  if (node.nodeType === 3) {
    const text = (node.textContent ?? '').replace(/\s+/g, ' ').trim();
    return text ? `${pad}"${text}"\n` : '';
  }
  if (node.nodeType !== 1) return '';
  const el = node as Element;
  const tag = el.tagName.toLowerCase();
  const kids = [...el.childNodes].map((kid) => snapshot(kid, depth + 1)).join('');
  return `${pad}<${tag}${attrsOf(el)}>\n${kids}`;
}

export function childSnapshots(el: Element): string[] {
  return [...el.childNodes].map((kid) => snapshot(kid)).filter(Boolean);
}

export function recorded(name: string, current: string): string {
  const file = path.join(DIR, `${name}.txt`);
  if (UPDATING) {
    fs.mkdirSync(DIR, { recursive: true });
    fs.writeFileSync(file, current);
    return current;
  }
  if (!fs.existsSync(file)) throw new Error(`no dialog recording __goldens__/${name}.txt`);
  return fs.readFileSync(file, 'utf8');
}

export function indent(text: string, depth: number): string {
  const pad = '  '.repeat(depth);
  return text.split('\n').map((line) => (line ? pad + line : line)).join('\n');
}

export interface FrameChange {
  addClasses?: readonly string[];
  removeClasses?: readonly string[];
  attrs?: Readonly<Record<string, string | null>>;
}

export function reframed(text: string, change: FrameChange): string {
  const cut = text.indexOf('\n');
  const head = text.slice(0, cut);
  const match = /^<([a-z][\w-]*)(.*)>$/.exec(head);
  if (!match) throw new Error(`not a frame line: ${head}`);
  const attrs = new Map<string, string>();
  for (const one of (match[2] ?? '').matchAll(/ ([^\s=]+)="([^"]*)"/g)) attrs.set(one[1]!, one[2]!);
  const classes = new Set((attrs.get('class') ?? '').split(' ').filter(Boolean));
  for (const name of change.addClasses ?? []) classes.add(name);
  for (const name of change.removeClasses ?? []) classes.delete(name);
  if (classes.size) attrs.set('class', [...classes].sort().join(' '));
  else attrs.delete('class');
  for (const [name, value] of Object.entries(change.attrs ?? {})) {
    if (value === null) attrs.delete(name);
    else attrs.set(name, value);
  }
  const line = [...attrs.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([name, value]) => ` ${name}="${value}"`).join('');
  return `<${match[1]}${line}>${text.slice(cut)}`;
}

export function recording(name: string): string {
  const file = path.join(DIR, `${name}.txt`);
  if (!fs.existsSync(file)) throw new Error(`no dialog recording __goldens__/${name}.txt`);
  return fs.readFileSync(file, 'utf8');
}

export function recordedParts(text: string): { frame: string; children: string[] } {
  const [frame = '', ...lines] = text.split('\n');
  const children: string[] = [];
  for (const line of lines) {
    if (!line) continue;
    const child = line.slice(2);
    if (!child.startsWith(' ')) children.push('');
    children[children.length - 1] += `${child}\n`;
  }
  return { frame: `${frame}\n`, children };
}
