
export const LOG_LEVELS = ['error', 'warn', 'info', 'debug'] as const;

export type LogLevel = (typeof LOG_LEVELS)[number];

export interface LogRecord {
  id: string;
  timestamp: string;
  level: LogLevel;
  source: string;
  event: string;
  fields: Record<string, string>;
  lines: string[];
  dropped_lines: number;
  traceback: boolean;
  continues: boolean;
  approx_time: boolean;
}

export interface LogPage {
  records: LogRecord[];
  head: string | null;
  /* there is nothing */
  before: string | null;
  gap: boolean;
  reset: boolean;
}

export interface LevelState {
  level: string;
  source: 'setting' | 'env';
  env_level: string;
  choices: string[];
  expires_at: string | null;
}

export interface LogSource {
  backfill(cursor: string): Promise<LogPage>;
  subscribe(onBatch: (page: LogPage) => void, onError?: (error: unknown) => void): () => void;
  readLevel(): Promise<LevelState>;
  setLevel(level: string | null): Promise<LevelState>;
}
