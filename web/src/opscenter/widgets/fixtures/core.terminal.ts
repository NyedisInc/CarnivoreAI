import { sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const SESSION = 'ses_billingapi';

export const terminalFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    [`GET /sessions/${SESSION}/pane-facts`]: {
      cwd: '/work/billing-api',
      cwd_display: '/work/billing-api',
      command: 'claude',
      git_branch: 'plan-change-migration',
      cols: 120,
      rows: 36,
    },
    [`GET /sessions/${SESSION}/token-usage`]: {
      state: 'ok',
      family: 'claude',
      model: 'claude-opus-5-5',
      model_display_name: 'Opus 5.5',
      model_cost_tier: 3,
      effort: 'high',
      input_tokens: 182000,
      output_tokens: 41000,
      cache_read_input_tokens: 1250000,
      cache_creation_input_tokens: 96000,
      total_tokens: 1569000,
      cost_estimate_usd: 6.42,
      context_used_tokens: 214000,
      context_window_tokens: 1000000,
      context_remaining_pct: 78.6,
      as_of: '2026-09-30T14:59:40.000Z',
      detail: null,
      account: null,
    },
  },
  empty: {
    'GET /sessions/list': sessionList(),
    [`GET /sessions/${SESSION}/pane-facts`]: { cwd: null, cwd_display: null, command: null, git_branch: null, cols: null, rows: null },
    [`GET /sessions/${SESSION}/token-usage`]: {
      state: 'absent', family: null, model: null, model_display_name: null, model_cost_tier: null, effort: null,
      input_tokens: null, output_tokens: null, cache_read_input_tokens: null, cache_creation_input_tokens: null,
      total_tokens: null, cost_estimate_usd: null, context_used_tokens: null, context_window_tokens: null,
      context_remaining_pct: null, as_of: '2026-09-30T14:59:40.000Z', detail: 'no transcript yet', account: null,
    },
  },
};
