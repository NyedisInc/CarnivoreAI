import type { DataRule, MenuRule } from './cell-menu-scan';

export interface MenuRuleEntry {
  folder: string;
  widgets: string[];
  rules: MenuRule[];
  why: string;
}

export const ALLOWED: readonly MenuRuleEntry[] = [
  {
    folder: 'terminal-live', widgets: ['core.terminal'], rules: ['body-menu-button'],
    why: 'the terminal kebab stays; its tool strip is the terminal head\'s toolbar',
  },
  {
    folder: 'terminal-group', widgets: ['core.terminal'], rules: ['menu-without-declared-actions'],
    why: 'the terminal component\'s tab strip: each tab\'s icon IS the component menu and "+" opens new tabs (frame-header.svelte.ts `strip`, #452, #514); the terminal is the one exception',
  },
  {
    folder: 'running-sessions', widgets: ['core.running-sessions'], rules: ['body-menu-button'],
    why: 'an ADD button, not a kebab: "+ new" in the header opens things to create, and the same items are declared to the one widget menu (`new:` actions)',
  },
];

export const KNOWN: readonly MenuRuleEntry[] = [];

export function excusedRules(folder: string): Set<MenuRule> {
  return new Set([...ALLOWED, ...KNOWN].filter((one) => one.folder === folder).flatMap((one) => one.rules));
}

export function excusedForWidget(widget: string): Set<MenuRule> {
  return new Set([...ALLOWED, ...KNOWN].filter((one) => one.widgets.includes(widget)).flatMap((one) => one.rules));
}

export interface DataKnownEntry {
  folder: string;
  file: string;
  rule: DataRule;
  why: 'widget-spec section 14';
}

export const DATA_KNOWN: readonly DataKnownEntry[] = [];

export const DATA_KNOWN_CEILING = 0;
