export interface ActivityLine {
  time: string;
  tag: string;
  message: string;
  source: string;
  highlights?: readonly (readonly [number, number])[];
  demo?: boolean;
}

export const activity: ActivityLine[] = [
  { time: '11:24:01', tag: 'session', message: 'C1 Building provider_accounts config block...', source: 'cloudecode' },
  { time: '11:23:56', tag: 'agent', message: 'Agent (Opus 5) thinking...', source: 'cloudecode' },
  { time: '11:23:41', tag: 'tool', message: 'Read file: auth.json (342 lines)', source: 'cloudecode' },
  { time: '11:22:18', tag: 'session', message: 'C2 Dispatching agent to research temp-folder flow', source: 'cloudecode-newui' },
  { time: '11:21:03', tag: 'system', message: '5 agents online | All systems operational', source: 'host' },
  { time: '11:19:47', tag: 'test', message: '108 tests passed  (+12)', source: 'cloudecode', highlights: [[0, 23]] },
  { time: '11:18:22', tag: 'plugin', message: 'rotate the staging credentials after the freeze ends', source: 'host' },
  { time: '11:17:09', tag: 'project', message: 'Switched to cloudecode-newui', source: 'cloudecode-newui' },
  { time: '11:16:40', tag: 'tool', message: 'Wrote file: session_routes.py (118 lines)', source: 'cloudecode', demo: true },
  { time: '11:15:58', tag: 'session', message: 'C3 Running test suite', source: 'Example App', demo: true },
  { time: '11:14:12', tag: 'agent', message: 'Agent (Sonnet 3.5) reading transcript tail', source: 'Example App', demo: true },
  { time: '11:13:03', tag: 'system', message: 'Archive ingest pass complete', source: 'host', demo: true },
  { time: '11:11:47', tag: 'test', message: '96 tests passed', source: 'cloudecode', highlights: [[0, 15]], demo: true },
  { time: '11:10:22', tag: 'tool', message: 'Read file: tokens.css (204 lines)', source: 'cloudecode-newui', demo: true },
  { time: '11:09:05', tag: 'plugin', message: 'GitHub plugin loaded', source: 'host', demo: true },
  { time: '11:07:31', tag: 'project', message: 'Opened quartz', source: 'quartz', demo: true },
];
