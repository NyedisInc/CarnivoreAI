import { projectList, recentRecords } from './made-up';
import type { WidgetFixtures } from './types';

export const closedSessionsFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/recent': { state: 'ok', sessions: recentRecords() },
    'GET /projects': projectList(),
  },
  empty: {
    'GET /sessions/recent': { state: 'ok', sessions: [] },
  },
};
