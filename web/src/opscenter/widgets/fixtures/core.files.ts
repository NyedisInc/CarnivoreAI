import { sessionList, TERMINAL_ROW_ID } from './made-up';
import type { RouteTable, WidgetFixtures } from './types';

const SESSION_UUID = '0edffbc5-38a8-4edc-8c9a-e9bab14a8b5d';

const GIT_ROUTE = 'GET /sessions/ses_billingapi/git-status';

function node(relPath: string, isDir: boolean, extra: Record<string, unknown> = {}): unknown {
  return {
    name: relPath.split('/').pop(), rel_path: relPath, is_dir: isDir, is_executable: false, is_sensitive: false,
    read_only: false, is_ignored: false, collapsed: false, children: [], children_loaded: !isDir, list_error: null, ...extra,
  };
}

const LEVELS: Record<string, Record<string, unknown[]>> = {
  workdir: {
    '': [
      node('.github', true), node('coverage', true, { is_ignored: true }), node('docs', true), node('src', true), node('tests', true),
      node('.env', false, { is_sensitive: true, is_ignored: true }), node('README.md', false), node('package.json', false), node('tsconfig.json', false),
    ],
    '.github': [node('.github/workflows', true)],
    '.github/workflows': [node('.github/workflows/ci.yml', false)],
    docs: [node('docs/architecture.md', false), node('docs/retry-policy.md', false)],
    coverage: [],
    src: [node('src/invoices', true), node('src/plans', true), node('src/webhooks', true), node('src/index.ts', false)],
    'src/invoices': [node('src/invoices/review-queue.ts', false), node('src/invoices/totals.ts', false)],
    'src/plans': [node('src/plans/migrate.ts', false), node('src/plans/catalog.ts', false)],
    'src/webhooks': [node('src/webhooks/retry.ts', false), node('src/webhooks/verify.ts', false)],
    tests: [node('tests/retry.test.ts', false), node('tests/totals.test.ts', false)],
  },
  user: {
    '': [
      node('agents', true), node('commands', true), node('hooks', true), node('plugins', true, { read_only: true }), node('rules', true), node('skills', true),
      node('CLAUDE.md', false), node('settings.json', false),
    ],
    agents: [node('agents/reviewer.md', false)],
    commands: [node('commands/ship.md', false)],
    hooks: [],
    plugins: [node('plugins/installed.json', false, { read_only: true })],
    rules: [node('rules/code-standards.md', false), node('rules/git-workflow.md', false)],
    skills: [node('skills/review', true)],
    'skills/review': [node('skills/review/SKILL.md', false)],
  },
};

function everything(root: string): { relPath: string; isDir: boolean }[] {
  return Object.values(LEVELS[root] ?? {}).flat().map((n) => {
    const entry = n as { rel_path: string; is_dir: boolean };
    return { relPath: entry.rel_path, isDir: entry.is_dir };
  });
}

function find(url: URL): unknown {
  const root = url.searchParams.get('root') ?? 'user';
  const q = (url.searchParams.get('q') ?? '').toLowerCase();
  const hits = everything(root).filter((e) => (e.relPath.split('/').pop() ?? '').toLowerCase().includes(q));
  const byPath = new Map<string, { node: Record<string, unknown>; parent: string }>();
  const top: Record<string, unknown>[] = [];
  for (const hit of hits) {
    const parts = hit.relPath.split('/');
    for (let i = 1; i <= parts.length; i += 1) {
      const path = parts.slice(0, i).join('/');
      if (byPath.has(path)) continue;
      const made = node(path, i < parts.length || hit.isDir, { children_loaded: true, filter_expanded: true }) as Record<string, unknown>;
      const parent = parts.slice(0, i - 1).join('/');
      byPath.set(path, { node: made, parent });
      if (parent) (byPath.get(parent)!.node.children as unknown[]).push(made);
      else top.push(made);
    }
  }
  return { root, tree: top, truncated: false, ignore_status: 'ok' };
}

function changed(path: string, kind: string, index: string, worktree: string): unknown {
  return { path, orig_path: null, index, worktree, kind, submodule: false };
}

function gitStatus(files: unknown[]): unknown {
  return {
    state: 'ok', repo_root: '/work/billing-api', working_dir_real: '/work/billing-api', repo_name: 'billing-api',
    branch: 'main', detached: false, head_short: 'a1b2c3d', unborn: false, upstream: 'origin/main', remote: 'origin',
    ahead: files.length ? 1 : 0, behind: 0,
    counts: { staged: files.length ? 1 : 0, unstaged: files.length ? 3 : 0, untracked: files.length ? 1 : 0, conflicted: 0 },
    files, truncated: 0, read_at: 1_760_000_000,
  };
}

function tree(populated: boolean): (url: URL) => unknown {
  return (url) => {
    const root = url.searchParams.get('root') ?? 'user';
    const path = url.searchParams.get('path') ?? '';
    return { root, tree: populated ? (LEVELS[root]?.[path] ?? []) : [], ignore_status: 'ok' };
  };
}

function table(populated: boolean): RouteTable {
  return {
    'GET /sessions/list': sessionList(),
    'GET /sessions/records': [{ id: TERMINAL_ROW_ID, session_uuid: SESSION_UUID, tmux_name: 'cloude_billing-api', lifecycle: 'running' }],
    'GET /config-files/tree': tree(populated),
    'GET /config-files/find': populated ? find : (url: URL) => ({ root: url.searchParams.get('root'), tree: [], truncated: false, ignore_status: 'ok' }),
    [GIT_ROUTE]: gitStatus(populated ? [
      changed('src/webhooks/retry.ts', 'modified', '.', 'M'),
      changed('src/invoices/review-queue.ts', 'added', 'A', '.'),
      changed('src/plans/migrate.ts', 'modified', 'M', '.'),
      changed('docs/retry-policy.md', 'untracked', '?', '?'),
      changed('src/legacy/stripe-v1.ts', 'deleted', '.', 'D'),
    ] : []),
  };
}

export const filesFixtures: WidgetFixtures = {
  data: table(true),
  empty: table(false),
};
