
import type { FixtureKind, RouteTable, WidgetFixtures } from './types';
import { common } from './common';
import { analyticsFixtures } from './core.analytics';
import { runningSessionsFixtures } from './core.running-sessions';
import { closedSessionsFixtures } from './core.closed-sessions';
import { projectsFixtures } from './core.projects';
import { skillsFixtures } from './core.skills';
import { pluginsFixtures } from './core.plugins';
import { themesFixtures } from './core.themes';
import { ledgerFixtures } from './core.ledger';
import { activityLogFixtures } from './core.activity-log';
import { notesFixtures } from './core.notes';
import { filesFixtures } from './core.files';
import { scheduledTasksFixtures } from './core.scheduled-tasks';
import { keepAwakeFixtures } from './core.keep-awake';
import { machineStatsFixtures } from './core.machine-stats';
import { changesFixtures } from './core.changes';
import { taskManagerFixtures } from './core.task-manager';
import { questionsFixtures } from './core.questions';
import { taskManagerListFixtures } from './core.task-list';
import { sessionContentsFixtures } from './core.session-contents';
import { terminalFixtures } from './core.terminal';
import { browserFixtures } from './core.browser';
import { statTileFixtures } from './core.stat-tiles';
import { timelineWidgetFixtures } from './core.timeline';
import { tasksFixtures } from './core.tasks';
import { bookmarksFixtures } from './core.bookmarks';
import { automationsFixtures } from './core.automations';
import { crosstalkFixtures } from './core.crosstalk';
import { pipelineFixtures } from './core.pipeline';
import { shellFixtures } from './core.shell';
import { stressTable } from './stress';

const ANALYTICS = 'core.analytics:';

const TABLES: Readonly<Record<string, WidgetFixtures>> = {
  'core.running-sessions': runningSessionsFixtures,
  'core.closed-sessions': closedSessionsFixtures,
  'core.projects': projectsFixtures,
  'core.skills': skillsFixtures,
  'core.plugins': pluginsFixtures,
  'core.themes': themesFixtures,
  'core.ledger': ledgerFixtures,
  'core.activity-log': activityLogFixtures,
  'core.notes': notesFixtures,
  'core.files': filesFixtures,
  'core.scheduled-tasks': scheduledTasksFixtures,
  'core.keep-awake': keepAwakeFixtures,
  'core.machine-stats': machineStatsFixtures,
  'core.changes': changesFixtures,
  'core.task-manager': taskManagerFixtures,
  'core.task-manager-mk2': taskManagerFixtures,
  'core.questions': questionsFixtures,
  'core.task-list': taskManagerListFixtures,
  'core.session-contents': sessionContentsFixtures,
  'core.terminal': terminalFixtures,
  'core.timeline': timelineWidgetFixtures,
  'core.browser': browserFixtures,
  'core.tasks': tasksFixtures,
  'core.tasks-all': tasksFixtures,
  'core.bookmarks': bookmarksFixtures,
  'core.bookmarks-all': bookmarksFixtures,
  'core.automations': automationsFixtures,
  'core.automations-all': automationsFixtures,
  'core.crosstalk': crosstalkFixtures,
  'core.pipeline': pipelineFixtures,
  'core.developer': pipelineFixtures,
  'core.task-manager-all': taskManagerListFixtures,
  'core.task-manager-mk2-all': taskManagerListFixtures,
  'core.shell': shellFixtures,
  'core.stat-running': statTileFixtures,
  'core.stat-sessions': statTileFixtures,
  'core.stat-projects': statTileFixtures,
  'core.stat-ledger': statTileFixtures,
  'core.stat-alive': statTileFixtures,
  'core.stat-subagents': statTileFixtures,
};

const REGISTERED = new Map<string, WidgetFixtures>();

export function registerFixtures(key: string, pair: WidgetFixtures): void {
  REGISTERED.set(key, pair);
}

function pairFor(key: string): WidgetFixtures | undefined {
  if (key.startsWith(ANALYTICS)) return analyticsFixtures(key.slice(ANALYTICS.length));
  return TABLES[key] ?? REGISTERED.get(key);
}

export function hasFixture(key: string): boolean {
  return pairFor(key) !== undefined;
}

export function ownRoutes(key: string, kind: 'data' | 'empty'): RouteTable {
  return pairFor(key)?.[kind] ?? {};
}

export function fixtureFor(key: string, kind: FixtureKind): RouteTable {
  if (kind === 'stress') return stressTable(fixtureFor(key, 'data'));
  const own = pairFor(key);
  return { ...common(kind), ...(own ? own[kind] : {}) };
}
