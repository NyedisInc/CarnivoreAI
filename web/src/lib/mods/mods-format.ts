import { t } from '../i18n/index.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { GroupResult, ModEntry, ModGroup } from './mods-api';

export function codeLabel(prefix: string, code: string, params: Record<string, string | number> = {}): string {
  const key = `${prefix}.${code}`;
  const text = t(key, params);
  return text === key ? code : text;
}

export function stateLabel(mod: ModEntry): string {
  return t(`mods.state.${mod.state}`, { on: mod.registered_in, total: mod.groups_total });
}

export function groupProblems(groups: (ModGroup | GroupResult)[]): string[] {
  return groups
    .filter((g) => g.status !== 'ok')
    .map((g) => codeLabel('mods.group', g.status, { label: 'label' in g ? g.label : g.real }));
}

export function refusalCode(error: unknown): string {
  if (!(error instanceof ApiError)) return '';
  if (error.code) return error.code;
  const detail = (error.payload as { detail?: { code?: unknown } } | null)?.detail;
  return typeof detail?.code === 'string' ? detail.code : '';
}

export function refusalText(error: unknown): string {
  const code = refusalCode(error);
  if (code) {
    const known = codeLabel('mods.refused', code);
    if (known !== code) return known;
  }
  return error instanceof Error ? error.message : String(error);
}
