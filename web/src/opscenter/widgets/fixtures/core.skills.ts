import { emptyCatalog, fullCatalog } from './catalog-items';
import type { WidgetFixtures } from './types';

export const skillsFixtures: WidgetFixtures = {
  data: { 'GET /catalog/items': fullCatalog(), 'POST /catalog/index/refresh': {}, 'POST /catalog/refresh': {} },
  empty: { 'GET /catalog/items': emptyCatalog(), 'POST /catalog/index/refresh': {}, 'POST /catalog/refresh': {} },
};
