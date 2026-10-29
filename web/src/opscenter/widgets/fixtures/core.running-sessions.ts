import { asleepRecords, projectList, sessionList } from './made-up';
import type { WidgetFixtures } from './types';

export const runningSessionsFixtures: WidgetFixtures = {
  data: {
    'GET /sessions/list': sessionList(),
    'GET /sessions/asleep': asleepRecords(),
    'GET /projects': projectList(),
  },
  empty: {
    'GET /sessions/list': [],
    'GET /sessions/asleep': [],
    'GET /projects': [],
  },
};
