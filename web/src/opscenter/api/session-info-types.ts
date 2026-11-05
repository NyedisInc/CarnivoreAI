
export interface AgentUpdateInfo {
  running: string;
  installed: string;
  ready: boolean;
}

export interface AutomationMark {
  automation_id: string;
  run_id: string;
  name: string;
}

export interface MessagingMark {
  directions: string[];
  held: number;
}

export interface BackgroundProcessesInfo {
  state: 'running' | 'none' | 'unknown';
  count?: number | null;
}

export interface McpServerHealthInfo {
  name: string;
  transport: 'stdio' | 'http' | 'sse' | 'proxy' | 'unknown';
  state: 'connected' | 'down' | 'needs_auth' | 'unknown';
  reason: string;
  source: 'first_hand' | 'client_log' | 'process' | 'probe' | 'transcript';
  detail?: string | null;
  at?: string | null;
  exact?: boolean;
}

export interface McpDropInfo {
  name: string;
  state: 'dropped' | 'failed' | 'needs_auth';
  at?: string | null;
  exact: boolean;
  source: 'transcript' | 'server' | 'client_log' | 'process' | 'probe';
}

export interface McpHealthInfo {
  servers: McpServerHealthInfo[];
  dropped: McpDropInfo[];
  carnivore?: { state: 'connected' | 'dropped' | 'unknown'; initialized_at?: string | null; last_request_at?: string | null } | null;
}

export interface LocalServerInfo {
  port: number;
  url: string;
  first_seen: string;
  last_seen: string;
}
