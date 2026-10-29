import { listingSnapshot } from '../opscenter/widgets/fixtures/sidebar-world';
import type { RouteTable } from '../opscenter/widgets/fixtures/types';

const LISTING_ROUTE = 'GET /sessions/listing';

export function withListing(table: RouteTable): RouteTable {
  return LISTING_ROUTE in table ? table : { ...table, [LISTING_ROUTE]: listingSnapshot(table) };
}
