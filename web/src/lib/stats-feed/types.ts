
export type FeedWindow = '1h' | '5h' | '1d' | '7d';

export const FEED_WINDOWS: readonly FeedWindow[] = ['1h', '5h', '1d', '7d'];

export type RateUnit = 'sec' | 'min' | 'hour' | 'day';
export const RATE_UNITS: readonly RateUnit[] = ['sec', 'min', 'hour', 'day'];

export interface FeedClasses {
  fresh: number;
  cache_write: number;
  cache_read: number;
  out: number;
}

export interface FeedSource {
  host_key: string;
  label: string;
  state: string;
  reason?: string;
  data_through?: number | null;
}

export interface FeedBody {
  v: number;
  rev: number;
  window: FeedWindow;
  bucket_seconds: number;
  start: number;
  now: number;
  state: string;
  in: (number | null)[];
  out: (number | null)[];
  totals: FeedClasses | null;
  rate: (FeedClasses & { span_seconds: number }) | null;
  sources: FeedSource[];
}
