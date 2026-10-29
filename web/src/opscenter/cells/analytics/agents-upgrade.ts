import { t } from '../../../lib/i18n/index.svelte';
import { AGENT_DEFAULT_WINDOW } from '../../viz/agents';
import type { ChartConfig } from './types';

const OLD_TITLE = 'tokens by agent kind';

export function isAgentKindRanking(chart: ChartConfig): boolean {
  const only = chart.series.length === 1 ? chart.series[0] : undefined;
  return Boolean(only) && only!.metric === 'total_tokens' && only!.operation === 'ranking' && only!.group_by === 'agent_kind'
    && (!chart.viz || chart.viz === 'timeline' || chart.viz === 'leaderboard');
}

export function agentsUpgrade(chart: ChartConfig): ChartConfig | null {
  if (!isAgentKindRanking(chart)) return null;
  return {
    ...chart, viz: 'agents', options: {},
    title: chart.title === OLD_TITLE ? t('analytics.agent_ranking') : chart.title,
    series: [{ metric: 'total_tokens', operation: 'timeline', group_by: 'conversation_id' }],
    range: { mode: 'global', preset: AGENT_DEFAULT_WINDOW },
    display: { type: 'line', legend: true },
  };
}
