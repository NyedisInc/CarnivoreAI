import { emptyCatalog, fullCatalog } from './catalog-items';
import type { WidgetFixtures } from './types';

export const pluginsFixtures: WidgetFixtures = {
  data: { 'GET /catalog/items': fullCatalog() },
  empty: { 'GET /catalog/items': emptyCatalog() },
};
