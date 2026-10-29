import { projectList, sessionList } from './made-up';
import type { WidgetFixtures } from './types';

export const projectsFixtures: WidgetFixtures = {
  data: {
    'GET /projects': projectList(),
    'GET /sessions/list': sessionList(),
  },
  empty: {
    'GET /projects': [],
    'GET /sessions/list': [],
  },
};
