<script lang="ts">
  import RankPanel, { type RankRow } from '../../opscenter/ui/RankPanel.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  const fires = (value: string): RankRow['metric'] => ({ value, unit: 'fires' });
  const rows: RankRow[] = [
    { id: 'a', name: 'work', line: 'run first for every feature or fix build request', icon: 'skill', metric: fires('312') },
    { id: 'b', name: 'design-engineer', line: 'front end design skills for any UI change', icon: 'skill', metric: fires('187') },
    { id: 'c', name: 'security-review', line: 'a complete security review of the pending changes on the current branch', icon: 'skill', metric: fires('96') },
    { id: 'd', name: 'merge-and-load', line: 'merging or pushing to trunk, the merge lock, machine load', icon: 'skill', metric: fires('54') },
    { id: 'e', name: 'full-suite', line: 'the whole python test suite on origin master', icon: 'skill', metric: null },
    { id: 'f', name: 'issues', line: 'every open github issue on this repo, classified', icon: 'skill', metric: fires('9') },
  ];
  const idle: RankRow[] = [
    { id: 'g', name: 'merge-and-load', line: 'merging or pushing to trunk, the merge lock, machine load', icon: 'skill', metric: { value: '74', unit: 'days' } },
    { id: 'h', name: 'full-suite', line: 'the whole python test suite on origin master', icon: 'skill', metric: { value: '51', unit: 'days' } },
    { id: 'i', name: 'issues', line: 'every open github issue on this repo, classified', icon: 'skill', metric: null },
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
