
export interface SessionRow {
  id: string;
  pty_pid: number | null;
  working_dir: string;
  status: string;
  created_at: string;
  last_activity: string;
  agent_type: string | null;
  pinned_theme: string | null;
  tmux_session: string | null;
  model: string | null;
  tmux_created_epoch?: number | null;
}

export interface LogEntry {
  timestamp: string;
  session_id: string;
  content: string;
  log_type: string;
}

export interface SessionStats {
  total_commands: number;
  uptime_seconds: number;
  log_lines: number;
  local_servers: number;
}

export interface UsageLimit {
  kind: 'session' | 'weekly' | 'weekly_model' | 'other';
  resets_at: string | null;
  message: string;
  since: string;
}

/* could not determine */
export interface SessionInfo {
  session: SessionRow;
  recent_logs: LogEntry[];
  stats: SessionStats | null;
  session_backend: string;
  tmux_session: string | null;
  host_key?: string;
  host_label?: string;
  host_state?: string;
  label: string | null;
  agent_type: string | null;
  agent_family: string | null;
  agent_family_source: string | null;
  agent_wrapper_label: string | null;
  pinned_theme: string | null;
  activity_status: string | null;
  activity_hint: string | null;
  unread: boolean | null;
  startup_gate: string | null;
  status_source: string | null;
  workflow_active?: boolean | null;
  usage_limit?: UsageLimit | null;
  project_id?: number | null;
  project_name?: string | null;
  session_row_id?: number | null;
  claude_session_uuid?: string | null;
  subagents_state?: string | null;
  subagents_running?: number | null;
  subagents_total?: number | null;
  timers_state?: string | null;
  timers_live?: number | null;
  timers_next_fire_at?: string | null;
  automations_state?: string | null;
  automations_total?: number | null;
  automations_enabled?: number | null;
  automations_next?: Array<{ name: string; enabled: boolean; next_fire_at: number | null }> | null;
  sleep_hold?: { reasons: string[]; text: string } | null;
  skills_state?: string | null;
  skills_fired?: number | null;
  skill_last?: { name: string; at?: string | null } | null;
  background_open?: number | null;
  account_id?: string | null;
}

export interface SessionRecord {
  session_uuid: string;
  host_key?: string | null;
  host_label?: string | null;
  origin: string;
  owned: boolean;
  lifecycle: string;
  title: string | null;
  working_dir: string | null;
  agent_type: string | null;
  agent_family: string | null;
  archived_at: string | null;
  created_at: string | null;
  last_work_at: string | null;
  project_id: number | null;
  tmux_name: string | null;
  closed_at?: string | null;
  closed_basis?: string | null;
  asleep?: boolean;
  unread?: boolean | null;
  pinned_theme?: string | null;
  id?: number | null;
  tmux_created_epoch?: number | null;
}

export interface RecentSessionsResponse {
  state: 'ok' | 'probe_unavailable' | 'never_probed' | string;
  sessions: SessionRecord[];
}

export interface ProjectResponse {
  id: number | null;
  name: string;
  path: string;
  description: string | null;
  root: string | null;
  work_at: string | null;
  archived_at: string | null;
  company_id?: number | null;
  company_name?: string | null;
  color?: string | null;
  parent_project_id?: number | null;
  has_image?: boolean;
  image_rev?: string | null;
  pack_state?: string | null;
  moved_to_label?: string | null;
}

export interface CatalogIndexStatus {
  serial: number | null;
  generated_at: string | null;
  as_of: string | null;
  degraded: boolean;
  stale: boolean;
  fetched_at: number | null;
  refusal: { code: string; detail: string | null } | null;
}

export interface CatalogInstalledRef {
  install_id: string;
  scope: string;
  project_path: string;
  version: string;
  update_available: boolean;
}

export interface CatalogItemView {
  id: string;
  kind: string;
  name: string;
  publisher: string;
  latest: string;
  card: Record<string, unknown>;
  installed: CatalogInstalledRef | null;
  untrusted: boolean;
}

export interface CatalogListResponse {
  index: CatalogIndexStatus;
  items: CatalogItemView[];
  untrusted: CatalogItemView[];
}

export interface ThemeManifest {
  id: string;
  name: string;
  description: string;
  author: string | null;
  version: string | null;
  cssVars: Record<string, string>;
  xterm: Record<string, string>;
  source: string;
  effects?: string | null;
  background?: { image: string; dim?: number | null } | null;
  characters?: { pack: string } | null;
  feedbackItemId?: string | null;
  publisher?: string | null;
  publisherGithub?: string | null;
}

export interface UsageWindow {
  kind: string;
  label: string;
  used_pct: number;
  window_seconds: number | null;
  resets_at: string | null;
}

export interface AccountUsage {
  id: string;
  name: string;
  short_name: string | null;
  provider: string;
  plan: string | null;
  identity: string | null;
  credential_state: string;
  fetched_at: string | null;
  next_poll_at: string | null;
  error: string | null;
  windows: UsageWindow[];
  color: string | null;
  managed: boolean;
  login_expires_at?: string | null;
  poke?: { state?: string | null; last_at?: string | null; error?: string | null } | null;
  setup_complete?: boolean | null;
}

export interface LedgerTotalWindow {
  kind: string;
  label: string;
  used_pct: number;
  resets_at: string | null;
  accounts: number;
}

export interface LedgerTotal {
  accounts: number;
  windows: LedgerTotalWindow[];
}

export interface LedgerSnapshot {
  accounts: AccountUsage[];
  total: LedgerTotal;
  loop: { alive: boolean; last_pass_at: string | null };
}

export type TokenUsageState = 'ok' | 'absent' | 'unchecked';

export type TokenUsageFamily = 'claude' | 'codex';

/* could not be determined */
export interface SessionTokenUsage {
  state: TokenUsageState;
  family: TokenUsageFamily | null;
  model: string | null;
  model_display_name: string | null;
  model_cost_tier: number | null;
  effort: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_input_tokens: number | null;
  cache_creation_input_tokens: number | null;
  total_tokens: number | null;
  cost_estimate_usd: number | null;
  context_used_tokens: number | null;
  context_window_tokens: number | null;
  context_remaining_pct: number | null;
  as_of: string;
  detail: string | null;
  account: AccountUsage | null;
}

export interface Toast {
  id: string;
  session_id: string;
  kind: string;
  title: string;
  body: string | null;
  session_label: string | null;
  session_name: string | null;
  created_at: string | null;
  acknowledged: boolean;
}

export interface EventFrame {
  type: string;
  toast?: Toast;
  toast_id?: string;
  session_id?: string;
  tmux_session?: string | null;
  activity_status?: string | null;
  unread?: boolean | null;
  startup_gate?: string | null;
  new_name?: string;
  reason?: string;
  /* could not determine */
  server_version?: string;
  client_build?: string;
}

/* could not be read */
export interface SessionPaneFacts {
  cwd: string | null;
  cwd_display: string | null;
  command: string | null;
  git_branch: string | null;
  cols: number | null;
  rows: number | null;
}

export interface SessionGitFile {
  path: string;
  orig_path: string | null;
  index: string;
  worktree: string;
  kind: 'modified' | 'added' | 'deleted' | 'renamed' | 'copied' | 'typechange' | 'untracked' | 'conflicted';
  submodule: boolean;
}

export interface SessionGitDiff {
  state: 'ok' | 'unknown' | 'remote';
  path?: string | null;
  text: string;
  truncated: boolean;
  untracked: boolean;
  binary: boolean;
  sensitive: boolean;
  directory: boolean;
}

export interface SessionGitStatus {
  state: 'ok' | 'not_a_repo' | 'unknown' | 'remote';
  repo_root?: string | null;
  working_dir_real?: string | null;
  repo_name: string | null;
  branch: string | null;
  detached?: boolean;
  head_short?: string | null;
  unborn?: boolean;
  upstream?: string | null;
  remote?: string | null;
  ahead?: number | null;
  behind?: number | null;
  counts: { staged: number; unstaged: number; untracked: number; conflicted: number };
  files: SessionGitFile[];
  truncated: number;
  read_at: number | null;
}
