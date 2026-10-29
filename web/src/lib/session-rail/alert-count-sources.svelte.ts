/* last run failed */
import { huddle, holdAggregate, startTaskManager } from '../../cplugs/huddle/huddle.svelte';
import { AGGREGATE, needsYouTotal } from '../../cplugs/huddle/huddle-model';
import { actionableOfGroups } from '../../opscenter/cells/task-manager-mk2/mk2-actionable';
import { badgeStatuses } from '../../cplugs/huddle/task-manager-prefs.svelte';
import { taskManagerBadgeMenu } from '../../cplugs/huddle/task-manager-badge-menu';
import { startAttentionSources } from '../attention-kinds/read.svelte';
import { questionCount } from '../../opscenter/cells/questions/state.svelte';
import { holdList, listCount } from '../../opscenter/cells/task-list/state.svelte';
import { sessionGit, releaseSessionGit } from '../../opscenter/api/session-git.svelte';
import { sessionTasks, releaseSessionTasks, allSessionTasks, releaseAllSessionTasks, type SessionTasks } from '../../opscenter/api/session-tasks.svelte';
import { automationsList, releaseAutomationsList } from '../../opscenter/api/automations-widget.svelte';
import type { Resource } from '../../opscenter/api/poll.svelte';
import type { SessionGitStatus } from '../../opscenter/api/types';
import { registerAlertCount, type AlertCountSource } from './alert-counts';

let gitReads = $state.raw<Record<string, Resource<SessionGitStatus>>>({});
const gitHolds: Record<string, number> = {};

registerAlertCount('core.task-manager', {
  hold: () => { startTaskManager(); return () => {}; },
  read: (scope) => (scope?.projectId == null ? null : needsYouTotal(huddle.lists, String(scope.projectId), badgeStatuses())),
  menu: taskManagerBadgeMenu,
});
registerAlertCount('core.task-manager-all', {
  hold: () => { startTaskManager(); return () => {}; },
  read: () => needsYouTotal(huddle.lists, AGGREGATE, badgeStatuses()),
  menu: taskManagerBadgeMenu,
});
registerAlertCount('core.task-manager-mk2', {
  hold: () => { startTaskManager(); return holdAggregate(); },
  read: (scope) => (scope?.projectId == null ? null : actionableOfGroups(huddle.groups, String(scope.projectId))),
});
registerAlertCount('core.task-manager-mk2-all', {
  hold: () => { startTaskManager(); return holdAggregate(); },
  read: () => actionableOfGroups(huddle.groups, null),
});
const changedFilesCount: AlertCountSource = {
  hold: (scope) => {
    const id = scope?.sessionId;
    if (!id) return () => {};
    gitHolds[id] = (gitHolds[id] ?? 0) + 1;
    gitReads = { ...gitReads, [id]: sessionGit(id) };
    return () => {
      releaseSessionGit(id);
      const left = (gitHolds[id] ?? 1) - 1;
      if (left > 0) {
        gitHolds[id] = left;
        return;
      }
      delete gitHolds[id];
      const { [id]: _released, ...rest } = gitReads;
      gitReads = rest;
    };
  },
  read: (scope) => {
    const data = scope ? gitReads[scope.sessionId]?.data : null;
    return data?.state === 'ok' ? data.files.length + data.truncated : null;
  },
};
registerAlertCount('core.changes', changedFilesCount);
registerAlertCount('core.files', changedFilesCount);
registerAlertCount('core.task-list', {
  hold: () => holdList(),
  read: (_scope, options) => listCount(options),
});
registerAlertCount('core.questions', {
  hold: () => startAttentionSources(),
  read: (_scope, options) => questionCount(options),
});

export const openTasks = (list: SessionTasks): number => list.counts.pending + list.counts.in_progress;

let taskReads = $state.raw<Record<string, Resource<SessionTasks>>>({});
let allTaskRead = $state.raw<ReturnType<typeof allSessionTasks> | null>(null);
let automationRead = $state.raw<ReturnType<typeof automationsList> | null>(null);

registerAlertCount('core.tasks', {
  hold: (scope) => {
    const id = scope?.sessionId;
    if (!id) return () => {};
    taskReads = { ...taskReads, [id]: sessionTasks(id) };
    return () => {
      releaseSessionTasks(id);
      const { [id]: _released, ...rest } = taskReads;
      taskReads = rest;
    };
  },
  read: (scope) => {
    const data = scope ? taskReads[scope.sessionId]?.data : null;
    return data && (data.state === 'ok' || data.state === 'empty') ? openTasks(data) : null;
  },
});
registerAlertCount('core.tasks-all', {
  hold: () => {
    allTaskRead = allSessionTasks();
    return () => { releaseAllSessionTasks(); allTaskRead = null; };
  },
  read: () => {
    const data = allTaskRead?.data;
    return data ? data.sessions.reduce((n, list) => n + openTasks(list), 0) : null;
  },
});
registerAlertCount('core.automations-all', {
  hold: () => {
    automationRead = automationsList();
    return () => { releaseAutomationsList(); automationRead = null; };
  },
  read: () => {
    const data = automationRead?.data;
    return data ? data.automations.filter((a) => a.last_run?.status === 'failed').length : null;
  },
});
