import { t } from '../i18n/index.svelte';
import type { ApprovalDisplay } from './approvals-model';

export function wordOr(key: string, fallback: string, params?: Record<string, unknown>): string {
  const text = t(key, params);
  return text === key ? fallback : text;
}

export function headline(display: ApprovalDisplay): string {
  const verb = wordOr(`approvals.display.verb.${display.verb}`, display.verb.replace(/_/g, ' '));
  const obj = display.object ? wordOr(`approvals.display.object.${display.object}`, display.object) : '';
  return obj ? `${verb} ${obj}` : verb;
}

export function consequenceLines(display: ApprovalDisplay): string[] {
  return (display.consequences ?? []).map((row) =>
    wordOr(`approvals.display.c.${row.key}`, row.params?.text ?? row.key, row.params ?? {}));
}

export function detailLabel(key: string): string {
  return wordOr(`approvals.display.d.${key}`, key.replace(/_/g, ' '));
}

export function typedMatches(expected: string | null | undefined, typed: string): boolean {
  return !expected || typed === expected;
}

export function inUseLine(display: ApprovalDisplay): string {
  const use = display.in_use;
  if (!use || !use.parts.length) return '';
  const parts = use.parts.map((row) => {
    const params: Record<string, unknown> = { ...row.params };
    if (row.params?.count !== undefined) params.count = Number(row.params.count);
    return wordOr(`approvals.display.inuse.${row.key}`, row.key, params);
  });
  return `${t(use.tone === 'alert' ? 'approvals.display.inuse.label' : 'approvals.display.inuse.note')} ${parts.join(', ')}`;
}
