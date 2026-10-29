import type { BeastRules } from './grid-model';

const ROW_DEFAULTS: readonly (readonly [string, string, string, boolean, boolean])[] = [
  ['dev_channels', 'startup', 'devChannels', true, true],
  ['folder_trust', 'startup', 'folderTrust', true, true],
  ['external_imports', 'startup', 'externalImports', true, true],
  ['chrome_decline', 'startup', 'chromeDecline', true, true],
  ['claude_permission', 'prompt', 'claudePermission', false, true],
  ['codex_approval', 'prompt', 'codexApproval', false, true],
  ['agent_writes', 'writes', 'agentWrites', false, true],
];

export function rulesWith(over: Readonly<Record<string, boolean>> = {}, scope = 'projects'): BeastRules {
  const cells: Record<string, { value: boolean; default: boolean }> = {};
  for (const [, , stem, off, on] of ROW_DEFAULTS) {
    cells[`${stem}Off`] = { value: over[`${stem}Off`] ?? off, default: off };
    cells[`${stem}On`] = { value: over[`${stem}On`] ?? on, default: on };
  }
  return {
    rows: ROW_DEFAULTS.map(([id, kind, stem]) => ({
      id, kind, off: cells[`${stem}Off`]!.value, on: cells[`${stem}On`]!.value, mode: 'off', handled_now: cells[`${stem}Off`]!.value,
      cells: { off: `${stem}Off`, on: `${stem}On` },
    })),
    cells,
    trust_scope: scope,
    trust_scopes: ['projects', 'every'],
    unconfirmed_rows: ['claude_permission', 'codex_approval', 'agent_writes'],
    always_asks: ['questions', 'free_text', 'plan_approval', 'widening_yes', 'other_startup', 'always_waits', 'own_dialog', 'loop_breaker', 'inbox_tools'],
  };
}

export const RULES: BeastRules = rulesWith();
