import { TERMINAL_ROW_ID, projectList, sessionList } from './made-up';
import type { WidgetFixtures } from './types';

const ROUTE = `GET /sessions/${TERMINAL_ROW_ID}/contents`;
const CONFIG = '/home/dev/.claude';
const WORK = '/work/billing-api';

function openTarget(path: string): [string, string] | null {
  if (path.startsWith(`${WORK}/`)) return ['workdir', path.slice(WORK.length + 1)];
  return path.startsWith(`${CONFIG}/`) && !path.endsWith('.claude.json') ? ['user', path.slice(CONFIG.length + 1)] : null;
}

function item(name: string, scope: string, path: string, description = '', detail = ''): unknown {
  const target = openTarget(path);
  const lines = /^(\d+) lines/.exec(detail);
  return {
    name, scope, path, description, detail, lines: lines ? Number(lines[1]) : (target && path.endsWith('.md') ? 24 : null),
    open_root: target?.[0] ?? null, open_path: target?.[1] ?? null, status: path.endsWith('SKILL.md') || scope === 'plugin' ? 'available' : 'loaded',
  };
}

function answer(items: Record<string, unknown[]>): unknown {
  const kinds = ['instructions', 'skills', 'agents', 'commands', 'hooks', 'output_styles', 'settings', 'mcp', 'plugins'];
  return {
    session_uuid: 'made-up-uuid', row_id: TERMINAL_ROW_ID, family: 'claude', config_dir: CONFIG, working_dir: WORK,
    sections: kinds.map((kind) => ({ kind, items: items[kind] ?? [], truncated: false })),
  };
}

export const sessionContentsFixtures: WidgetFixtures = {
  data: {
    [ROUTE]: answer({
      instructions: [item('CLAUDE.md', 'global', `${CONFIG}/CLAUDE.md`, '', '42 lines'), item('CLAUDE.md', 'project', `${WORK}/CLAUDE.md`, '', '118 lines'),
        item('rules/testing.md', 'project', `${WORK}/.claude/rules/testing.md`, '', '9 lines')],
      skills: [item('release-notes', 'global', `${CONFIG}/skills/release-notes/SKILL.md`, 'draft release notes from merged changes'),
        item('invoice-check', 'project', `${WORK}/.claude/skills/invoice-check/SKILL.md`, 'verify an invoice export against the ledger'),
        item('pdf-fill', 'plugin', '/plugins/docs/skills/pdf-fill/SKILL.md', 'fill a PDF form', 'plugin docs')],
      agents: [item('reviewer', 'project', `${WORK}/.claude/agents/reviewer.md`, 'reviews a diff for risky changes')],
      commands: [item('deploy', 'project', `${WORK}/.claude/commands/deploy.md`, 'ship the current branch to staging')],
      hooks: [item('PreToolUse [Bash]', 'global', `${CONFIG}/settings.json`, '', 'command guard.sh')],
      settings: [item('settings.json', 'global', `${CONFIG}/settings.json`, '', 'hooks, permissions'), item('settings.local.json', 'project', `${WORK}/.claude/settings.local.json`, '', 'permissions')],
      mcp: [item('ledger', 'global', `${CONFIG}/.claude.json`, '', 'stdio npx'), item('docs', 'project', `${WORK}/.mcp.json`, '', 'http')],
      plugins: [item('docs', 'plugin', '/plugins/docs', '', 'v1.4.0 enabled')],
    }),
    'GET /sessions/list': sessionList(),
    'GET /projects': projectList(),
  },
  empty: {
    [ROUTE]: answer({ settings: [item('settings.json', 'global', `${CONFIG}/settings.json`, '', 'permissions')] }),
    'GET /sessions/list': sessionList(),
    'GET /projects': projectList(),
  },
};
