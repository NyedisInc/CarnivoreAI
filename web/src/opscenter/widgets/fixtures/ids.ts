
export const FIXTURE_CHART_PREFIX = 'fx-';

export function fixtureChartId(presetId: string): string {
  return FIXTURE_CHART_PREFIX + presetId.replace(/_/g, '-');
}
