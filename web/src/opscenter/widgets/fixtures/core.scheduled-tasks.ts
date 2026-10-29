import { ago, DAY, HOUR, MIN } from './clock';
import type { WidgetFixtures } from './types';

function task(name: string, description: string, schedule: string, lastAgo: number, nextIn: number, runs: number): unknown {
  return {
    id: name,
    name,
    description,
    file_state: 'ok',
    schedule,
    schedule_source: 'frontmatter',
    next_run_at: ago(-nextIn),
    last_run_at: ago(lastAgo),
    runs_recorded: runs,
    updated_at: ago(9 * DAY),
    host_key: null,
    host_label: null,
  };
}

export const scheduledTasksFixtures: WidgetFixtures = {
  data: {
    'GET /scheduled-tasks': {
      state: 'ok',
      tasks: [
        task('nightly-backup-check', 'verify last night backups restored', '0 2 * * *', 13 * HOUR, 11 * HOUR, 96),
        task('weekly-cost-report', 'summarise model spend per project', '0 9 * * 1', 2 * DAY, 5 * DAY, 18),
        task('docs-link-check', 'find broken links in the docs site', '30 6 * * *', 8 * HOUR + 30 * MIN, 15 * HOUR, 60),
        task('stale-branch-sweep', 'list branches idle for 30 days', '0 8 * * 5', 4 * DAY, 3 * DAY, 11),
      ],
      total: 4,
      truncated: false,
      runs_truncated: false,
      detail: '',
      as_of: ago(MIN),
    },
  },
  empty: {
    'GET /scheduled-tasks': { state: 'ok', tasks: [], total: 0, truncated: false, runs_truncated: false, detail: '', as_of: ago(MIN) },
  },
};
