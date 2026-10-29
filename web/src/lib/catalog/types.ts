
export interface CatalogSignature {
    key_id?: string | null;
    [key: string]: unknown;
}

/* was not found */
export interface CatalogReview {
    status?: 'reviewed' | 'unavailable' | null;
    summary?: string | null;
    warnings?: CatalogReviewWarning[] | null;
    verdict?: string | null;
    override?: CatalogReviewOverride | null;
    [key: string]: unknown;
}

export interface CatalogReviewOverride {
    reason?: string | null;
    by?: string | null;
    at?: string | null;
    [key: string]: unknown;
}

export interface CatalogReviewWarning {
    kind?: string | null;
    detail?: string | null;
    file?: string | null;
    line?: number | null;
    [key: string]: unknown;
}

export interface CatalogGrade {
    grade?: string | null;
    checked?: number | null;
    failed?: CatalogGradeFailure[] | null;
    not_graded?: string[] | null;
}

export interface CatalogGradeFailure {
    rule?: string | null;
    level?: string | null;
    detail?: string | null;
}

export interface CatalogVersion {
    v?: string | null;
    digest?: string | null;
    size?: number | null;
    files?: number | null;
    scripts?: number | null;
    published_at?: string | null;
    sig?: CatalogSignature | null;
    review?: CatalogReview | null;
    grade?: CatalogGrade | null;
    [key: string]: unknown;
}

export interface CatalogCardBlock {
    title?: string | null;
    brief?: string | null;
    icon?: string | null;
    tags?: string[] | null;
    media?: { sha256?: string | null; w?: number; h?: number; source?: string } | null;
    [key: string]: unknown;
}

export interface CatalogCost {
    desc_tokens?: number | null;
    body_tokens?: number | null;
    estimator?: string | null;
}

export interface FileChange {
    path: string;
    status: 'added' | 'removed' | 'changed';
    old_size?: number | null;
    new_size?: number | null;
    diff?: string | null;
    diff_reason?: 'binary' | 'large' | null;
    diff_truncated?: boolean;
}

export interface UpdateDiff {
    from_version: string;
    to_version: string;
    changes: FileChange[];
    unchanged: number;
}

export interface ContentsFile {
    path: string;
    size: number;
    kind: 'text' | 'binary' | 'large';
}

export interface CatalogContents {
    item_id: string;
    version: string;
    digest: string;
    files: ContentsFile[];
    total_bytes: number;
    body: string;
    body_truncated: boolean;
}

export interface CatalogDeprecation {
    superseded_by?: string | null;
}

export interface CatalogItem {
    id?: string | null;
    kind?: string | null;
    name?: string | null;
    publisher?: string | null;
    latest?: string | null;
    card?: CatalogCardBlock | null;
    fm?: Record<string, unknown> | null;
    versions?: CatalogVersion[] | null;
    cost?: CatalogCost | null;
    fm_keys?: string[] | null;
    related?: string[] | null;
    deprecated?: CatalogDeprecation | null;
    featured_rank?: number | null;
    first_published_at?: string | null;
    [key: string]: unknown;
}

export interface CatalogIndexState {
    serial?: number | null;
    generated_at?: string | null;
    as_of?: string | null;
    degraded?: boolean | null;
    [key: string]: unknown;
}

export interface CatalogListResponse {
    index?: CatalogIndexState | null;
    items?: CatalogItem[] | null;
    untrusted?: CatalogItem[] | null;
    [key: string]: unknown;
}

export interface CatalogItemResponse {
    index?: CatalogIndexState | null;
    item?: CatalogItem | null;
    [key: string]: unknown;
}

export interface InstalledItem {
    install_id?: string | null;
    item_id?: string | null;
    kind?: string | null;
    name?: string | null;
    publisher?: string | null;
    version?: string | null;
    digest?: string | null;
    scope?: 'global' | 'project' | null;
    project_path?: string | null;
    source_index_url?: string | null;
    auto_update?: boolean | null;
    revision?: number | null;
    update_available?: boolean | null;
    latest_version?: string | null;
    targets?: InstalledTarget[] | null;
    drift?: SkillDrift | null;
    forked?: boolean | null;
    members?: LoadoutMemberResult[] | null;
    complete?: boolean | null;
    [key: string]: unknown;
}

export interface InstalledTarget {
    harness?: string | null;
    path?: string | null;
    [key: string]: unknown;
}

export interface InstalledListResponse {
    items?: InstalledItem[] | null;
    [key: string]: unknown;
}

export interface PreviewFile {
    path?: string | null;
    size?: number | null;
    exec?: boolean | null;
    [key: string]: unknown;
}

export interface NameTakenChoice {
    choice?: string | null;
    name?: string | null;
    added?: number | null;
    changed?: number | null;
    removed?: number | null;
    bytes_delta?: number | null;
    [key: string]: unknown;
}

export interface LoadoutMemberPreview {
    item_id?: string | null;
    version?: string | null;
    kind?: string | null;
    title?: string | null;
    scripts?: number | null;
    installed?: boolean | null;
    instructions_write?: boolean | null;
    instructions_details?: string[] | null;
    instructions_more?: number | null;
    [key: string]: unknown;
}

export interface LoadoutMemberResult {
    item_id?: string | null;
    version?: string | null;
    state?: string | null;
    code?: string | null;
    detail?: string | null;
    install_id?: string | null;
    [key: string]: unknown;
}

export interface McpServer {
    name: string;
    command: string;
    args: string[];
    env_keys: string[];
}

export interface InstallPreview {
    body?: string | null;
    files?: PreviewFile[] | null;
    publisher?: string | null;
    version?: string | null;
    key_id?: string | null;
    pinned?: boolean | null;
    index_host?: string | null;
    digest_prefix?: string | null;
    digest?: string | null;
    /* undefined outside a secure context */
    body_sha?: string | null;
    total_bytes?: number | null;
    review?: CatalogReview | null;
    choices?: NameTakenChoice[] | null;
    loadout_members?: LoadoutMemberPreview[] | null;
    mcp_servers?: McpServer[] | null;
    plan_token?: string | null;
    diff?: UpdateDiff | null;
    mod_report?: ModReport | null;
    mod_report_sha?: string | null;
    mod_flagged_ack_needed?: boolean | null;
    mod_settings_groups?: string[] | null;
    cplug_facts?: CplugFactsData | null;
    cplug_facts_sha?: string | null;
    [key: string]: unknown;
}

export interface CplugFactsData {
    id: string;
    name: string;
    description: string;
    version: string;
    entry: string;
    files: number;
    bytes: number;
    permissions: { name: string; risk: string; reason: string }[];
    tools: { name: string; gate: string; description: string; input_schema: unknown }[];
    network_hosts: { host: string; reason: string; methods: string[]; paths: string[]; secret: string }[];
    lan_hosts: { entry: string; reason: string; methods: string[]; paths: string[] }[];
    secrets: { name: string; label: string; hosts: string[] }[];
}

export interface ModReport {
    claude_version: string;
    hooks: { module: string; events: string[] }[];
    calls: { module: string; calls: string[] }[];
    gating: { module: string; pattern: string; hook: string; has_catch: boolean }[];
    warnings: string[];
    spends_plan_usage: boolean;
    notes_raw: string[];
}

export type InstallScope = 'global' | 'project';

export interface InstallConsent {
    digest: string;
    body_sha: string;
    scripts: true;
    mod_trust?: boolean;
    mod_flagged_ack?: boolean;
    cplug_accepted?: boolean;
    cplug_facts_sha?: string;
    mod_report_sha?: string;
}

export interface InstallRequest {
    item_id: string;
    scope: InstallScope;
    project_path?: string | null;
    choice?: string | null;
    plan_token?: string | null;
    consent?: InstallConsent | null;
    member_consents?: Record<string, InstallConsent> | null;
    harnesses?: ('claude' | 'codex')[] | null;
    create_roots?: boolean;
    one_click?: boolean;
}

export interface PatchInstalledRequest {
    auto_update: boolean;
    expected_revision: number;
}

export interface UpdateInstalledRequest {
    expected_revision: number;
    consent?: UpdateConsent | null;
}

export interface UpdateConsent {
    body_sha: string;
    digest?: string;
    scripts?: true;
}

export interface RatingReview {
    login?: string | null;
    stars?: number | null;
    text?: string | null;
    updated_at?: number | null;
    review_ref?: string | null;
    author?: string | null;
    publisher?: boolean | null;
    reported_installing?: boolean | null;
    [key: string]: unknown;
}

/* could not be read */
export interface ItemRatingWrite {
    item_id?: string | null;
    count?: number | null;
    average?: number | null;
    histogram?: Record<string, number> | null;
    your_stars?: number | null;
    removed?: boolean | null;
}

export interface RatingWriteBody {
    stars: number;
    text?: string;
}

export interface ItemRatings {
    item_id?: string | null;
    count?: number | null;
    average?: number | null;
    histogram?: Record<string, number> | null;
    reviews?: RatingReview[] | null;
    [key: string]: unknown;
}

export interface SubmissionFile {
    path?: string | null;
    /* could not measure */
    size?: number | null;
    [key: string]: unknown;
}

export interface SubmissionRefusal {
    code?: string | null;
    detail?: string | null;
    path?: string | null;
    [key: string]: unknown;
}

export interface SubmissionPreview {
    name?: string | null;
    version?: string | null;
    file_count?: number | null;
    total_bytes?: number | null;
    files?: SubmissionFile[] | null;
    refusals?: SubmissionRefusal[] | null;
    [key: string]: unknown;
}

export interface ItemInstalls {
    item_id?: string | null;
    count?: number | null;
    by_version?: Record<string, number> | null;
    [key: string]: unknown;
}

export interface CatalogAuthSession {
    signed_in?: boolean | null;
    kind?: string | null;
    login?: string | null;
    provider?: string | null;
    mailbox_proof?: EmailFlowStart | null;
    [key: string]: unknown;
}

export interface EmailFlowStart {
    flow_id?: string | null;
    destination?: string | null;
    expires_in?: number | null;
    [key: string]: unknown;
}

export interface DeviceFlowStart {
    flow_id?: string | null;
    user_code?: string | null;
    verification_uri?: string | null;
    interval?: number | null;
    expires_in?: number | null;
    [key: string]: unknown;
}

export interface OneShotResult {
    pasted_bytes?: number | null;
    stripped_count?: number | null;
    submitted?: boolean | null;
    [key: string]: unknown;
}

export type SheetOutcome =
    | { outcome: 'installed'; row: InstalledItem }
    | { outcome: 'refused'; code: string | null };

export interface SkillUsage {
    skill?: string | null;
    state?: 'measured' | 'not_measured' | string | null;
    fired_7d?: number | null;
    fired_30d?: number | null;
    fired_90d?: number | null;
}

export interface SkillDrift {
    state: 'clean' | 'drifted' | 'missing' | 'unknown';
    changed_files?: string[] | null;
    checked_at?: number | null;
}

export interface AutopsySpan {
    fired_at?: string | null;
    session: string;
    tool_calls: number;
    tool_errors: number;
    interrupted: boolean;
    tokens?: number | null;
    correction?: boolean | null;
    next_excerpt?: string | null;
    ended: string;
    categories?: string[];
    digest?: string | null;
}

export interface SkillAutopsy {
    skill: string;
    days: number;
    state: 'measured' | 'not_measured';
    fires?: number | null;
    spans_measured?: number | null;
    tool_calls?: number | null;
    tool_errors?: number | null;
    interrupts?: number | null;
    corrections?: number | null;
    corrections_measured?: number | null;
    tokens_total?: number | null;
    categories?: Record<string, number>;
    undisclosed?: string[] | null;
    recent?: AutopsySpan[];
}

export interface CatalogDeviceSession {
    sid: string;
    client: string;
    label: string;
    created_at: number;
    last_refresh_at: number;
    current: boolean;
}

export interface CatalogDeviceSessions {
    sessions: CatalogDeviceSession[];
}

export interface CatalogRevoked {
    revoked: number;
}

export interface CatalogDeleteResult {
    deleted: boolean;
    deleting: boolean;
}

export type CatalogAccountExport = Record<string, unknown>;


export interface CatalogMeta {
    visible: number;
    total: number;
    asOf: string | null;
    degraded: boolean;
}

export interface ThemePaletteEntry {
    digest: string;
    version: string;
    cssVars: Record<string, string>;
    xterm: Record<string, string>;
    ascii: boolean;
}

export interface ThemePalettesResponse {
    items: Record<string, ThemePaletteEntry>;
    pending: string[];
}
