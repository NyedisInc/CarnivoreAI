import type { WidgetFixtures } from './types';

const STATUS_ROUTE = 'GET /sessions/ses_billingapi/git-status';

function file(path: string, kind: string, index: string, worktree: string): unknown {
  return { path, orig_path: null, index, worktree, kind, submodule: false };
}

function status(files: unknown[]): unknown {
  return {
    state: 'ok',
    repo_root: '/work/billing-api',
    working_dir_real: '/work/billing-api',
    repo_name: 'billing-api',
    branch: 'main',
    detached: false,
    head_short: 'a1b2c3d',
    unborn: false,
    upstream: 'origin/main',
    remote: 'origin',
    ahead: 1,
    behind: 0,
    counts: { staged: 1, unstaged: 3, untracked: files.length > 0 ? 1 : 0, conflicted: 0 },
    files,
    truncated: 0,
    read_at: 1_760_000_000,
  };
}

export const changesFixtures: WidgetFixtures = {
  data: {
    [STATUS_ROUTE]: status([
      file('src/webhooks/retry.ts', 'modified', '.', 'M'),
      file('src/invoices/review-queue.ts', 'added', 'A', '.'),
      file('src/plans/migrate.ts', 'modified', 'M', '.'),
      file('docs/retry-policy.md', 'untracked', '?', '?'),
      file('src/legacy/stripe-v1.ts', 'deleted', '.', 'D'),
    ]),
  },
  empty: {
    [STATUS_ROUTE]: status([]),
  },
};
