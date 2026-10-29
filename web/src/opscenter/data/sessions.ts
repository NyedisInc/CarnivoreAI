
export interface RunningSession {
  id: string;
  task: string;
  agent: string;
  project: string;
  elapsedSeconds: number;
  status: string;
  demo?: boolean;
}

export interface ClosedSession {
  id: string;
  task: string;
  agent: string;
  durationSeconds: number;
  ended: string;
  status: string;
  demo?: boolean;
}

export const running: RunningSession[] = [
  { id: 'C1', task: 'provider_accounts config..', agent: 'Opus 5', project: 'cloudecode', elapsedSeconds: 683, status: 'Running' },
  { id: 'C2', task: 'move session to project', agent: 'Haiku 4.5', project: 'cloudecode-newui', elapsedSeconds: 312, status: 'Running' },
  { id: 'C3', task: 'test suite + fixes', agent: 'Sonnet 3.5', project: 'Lantern App', elapsedSeconds: 161, status: 'Running' },
];

export const closed: ClosedSession[] = [
  { id: 'C0', task: 'fix auth token refresh', agent: 'Opus 5', durationSeconds: 494, ended: '10:47', status: 'Completed' },
  { id: 'C-1', task: 'add project switcher UI', agent: 'Sonnet 3.5', durationSeconds: 903, ended: '09:12', status: 'Completed' },
  { id: 'C-2', task: 'refactor agent manager', agent: 'Haiku 4.5', durationSeconds: 415, ended: '08:41', status: 'Completed' },
  { id: 'C-3', task: 'improve logging pipeline', agent: 'Opus 5', durationSeconds: 721, ended: '07:18', status: 'Completed' },
  { id: 'C-4', task: 'update documentation', agent: 'Sonnet 3.5', durationSeconds: 267, ended: '06:53', status: 'Completed' },
  { id: 'C-5', task: 'split settings routes', agent: 'Opus 5', durationSeconds: 1104, ended: '06:02', status: 'Completed', demo: true },
  { id: 'C-6', task: 'wire theme consent ladder', agent: 'Haiku 4.5', durationSeconds: 338, ended: '05:37', status: 'Completed', demo: true },
  { id: 'C-7', task: 'rebuild archive ingester', agent: 'Sonnet 3.5', durationSeconds: 1526, ended: '04:44', status: 'Completed', demo: true },
];
