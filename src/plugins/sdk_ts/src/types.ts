export type ToolGate = "read" | "inbox";

export type RpcErrorCode =
  | -32001
  | -32002
  | -32003
  | -32004
  | -32005
  | -32006 // timeout
  | -32007 // disabled
  | -32600
  | -32601
  | -32602
  | -32603;

export interface HostErrorData {
  reason?: string;
  permission?: string;
  limit?: string;
  keys?: string[];
  [key: string]: unknown;
}

export interface JsonRpcRequest {
  jsonrpc?: "2.0";
  id?: number;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: HostErrorData;
}

export interface JsonRpcResponse {
  jsonrpc?: "2.0";
  id: number;
  result?: unknown;
  error?: JsonRpcError;
}

export type RpcSender = (method: string, params: Record<string, unknown>) => Promise<unknown>;

export interface ToolCaller {
  kind?: string;
  session_ref?: string | null;
  owner_token?: string;
  [key: string]: unknown;
}

export interface ToolSpec {
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
  gate?: ToolGate;
}

export type ToolHandler = (args: Record<string, unknown>, caller: ToolCaller) => Promise<unknown> | unknown;

export interface RouteRequest {
  route: string;
  method: string;
  path_params?: Record<string, string>;
  query?: Record<string, string[]>;
  body?: unknown;
  actor?: string;
  owner_token?: string;
  session_ref?: string;
  [key: string]: unknown;
}

export interface RouteResponse {
  status: number;
  body: unknown;
}

export type RouteHandler = (req: RouteRequest) => Promise<RouteResponse> | RouteResponse;
export type EventHandler = (seq: number | null | undefined, payload: unknown) => Promise<void> | void;
export type WebhookHandler = (
  payload: unknown,
  seq: number | null | undefined,
  meta: { hook: string; family: string },
) => Promise<unknown> | unknown;
export type TimerHandler = (scheduledFor: number) => Promise<void> | void;
export type UiHandler = (params: Record<string, unknown>) => Promise<UiDocument> | UiDocument;
export type CommandHandler = (params: Record<string, unknown>) => Promise<unknown> | unknown;
export type ServiceHandler = (args: Record<string, unknown>, meta: { service: string; method: string }) => Promise<unknown> | unknown;

export interface ChannelEvent {
  type_id?: string;
  kind?: string;
  title?: string;
  body?: string;
  severity?: string;
  project?: unknown;
  session?: string;
  ts?: number;
  [key: string]: unknown;
}

export type ChannelHandler = (
  event: ChannelEvent,
  config: Record<string, unknown>,
) => Promise<unknown> | unknown;

export interface InitializeParams {
  api_version?: string;
  app_version?: string;
  plugin_id?: string;
  install_name?: string;
  granted?: string[];
  data_dir?: string;
  settings?: Record<string, unknown>;
  tier?: string;
  locale?: string;
}

export interface InitializeResult {
  api_version: string;
  capabilities: {
    tools: boolean;
    routes: boolean;
    events: boolean;
    timers: boolean;
    services: boolean;
  };
  subscriptions: string[];
}

export interface SessionRow {
  id: string;
  session_row_id?: string;
  label?: string;
  project_id?: number;
  activity_status?: string;
  unread?: boolean;
  startup_gate?: string | null;
  agent_family?: string;
  created_at?: string;
  last_activity?: string;
  [key: string]: unknown;
}

export interface ProjectRow {
  id: number;
  name: string;
}

export interface FetchOptions {
  method?: string;
  headers?: Record<string, string>;
  body?: string | null;
  json?: unknown;
}

export interface FetchResponse {
  status: number;
  headers: Record<string, string>;
  body: string;
  truncated?: boolean;
}

export type AiCapability = "chat" | "embed" | string;

export interface AiCallInput {
  [key: string]: unknown;
}

export interface FlowRunOptions {
  seed?: string;
  start?: number;
  end?: number;
  refresh?: boolean;
}

export interface FlowFeedOptions {
  seed?: string;
  start?: number;
  cursor?: number;
}

export interface UiNode {
  type: string;
  [key: string]: unknown;
}

export interface UiDocument {
  schema: number;
  root: UiNode;
  data?: Record<string, unknown>;
}
