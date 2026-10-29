<script lang="ts">
  import RankPanel, { type RankRow } from '../../opscenter/ui/RankPanel.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  const fires = (value: string): RankRow['metric'] => ({ value, unit: 'fires' });
  const rows: RankRow[] = [
    { id: 'a', name: 'ship-it', line: 'run first for every release request', icon: 'skill', metric: fires('141') },
    { id: 'b', name: 'ui-polish', line: 'front end styling help for any screen change', icon: 'skill', metric: fires('88') },
    { id: 'c', name: 'code-review', line: 'a careful review of the pending changes on the current branch', icon: 'skill', metric: fires('63') },
    { id: 'd', name: 'branch-sync', line: 'keeping a feature branch current with the main line', icon: 'skill', metric: fires('27') },
    { id: 'e', name: 'run-tests', line: 'the whole test suite on the main line', icon: 'skill', metric: null },
    { id: 'f', name: 'triage', line: 'every open issue on this repo, sorted by area', icon: 'skill', metric: fires('5') },
  ];
  const idle: RankRow[] = [
    { id: 'g', name: 'branch-sync', line: 'keeping a feature branch current with the main line', icon: 'skill', metric: { value: '46', unit: 'days' } },
    { id: 'h', name: 'run-tests', line: 'the whole test suite on the main line', icon: 'skill', metric: { value: '38', unit: 'days' } },
    { id: 'i', name: 'triage', line: 'every open issue on this repo, sorted by area', icon: 'skill', metric: null },
  ];
  const notMeasured = t('opscenter.session.mark.not_measured');
</script>

<div class="sg-rank-demo" style="display: grid; gap: 16px">
  <RankPanel
    label="skills by fires"
    {rows}
    ranked
    columns={{ name: 'skill', metric: 'fires, last 90 days' }}
    viewAll="view all"
    onViewAll={() => {}}
    {notMeasured}
  />
  <RankPanel label="unused 31 to 90 days" rows={idle} columns={{ name: 'skill', metric: 'unused for' }} {notMeasured} />
</div>
