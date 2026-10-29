
export interface ProjectRow {
  id: string;
  name: string;
  underline?: boolean;
  type: string;
  updatedMinutes: number;
  sessions: number;
  path: string;
  demoColumns: readonly string[];
}

const DEMO = ['sessions', 'path'] as const;

export const projects: ProjectRow[] = [
  { id: 'orchard-api', name: 'orchard-api', type: 'Project', updatedMinutes: 15, sessions: 3, path: '~/Dev/orchard-api', demoColumns: DEMO },
  { id: 'kite-web', name: 'Kite Web', type: 'Project', updatedMinutes: 45, sessions: 2, path: '~/Dev/kite-web', demoColumns: DEMO },
  { id: 'ledger-tools', name: 'ledger-tools', underline: true, type: 'Project', updatedMinutes: 130, sessions: 1, path: '~/Dev/ledger-tools', demoColumns: DEMO },
  { id: 'meadow', name: 'Meadow', type: 'Project', updatedMinutes: 600, sessions: 0, path: '~/Dev/meadow', demoColumns: DEMO },
  { id: 'quartz-cli', name: 'quartz-cli', type: 'Project', updatedMinutes: 1200, sessions: 2, path: '~/Dev/quartz-cli', demoColumns: DEMO },
  { id: 'sample-docs', name: 'sample-docs', type: 'Project', updatedMinutes: 4320, sessions: 0, path: '~/Dev/sample-docs', demoColumns: DEMO },
  { id: 'tide-mobile', name: 'Tide Mobile', type: 'Project', updatedMinutes: 10080, sessions: 1, path: '~/Dev/tide-mobile', demoColumns: DEMO },
];
