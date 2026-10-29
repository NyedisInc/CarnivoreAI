import { ApiError, authFetch, type Translate } from '../sdk';

export const ROUTE = '/cplugs/crate';
export const JOBS_FAMILY = 'cplug.crate.jobs';
const ERROR_KEY = 'cplug.crate.error.';

export type Fetcher = typeof authFetch;

export interface FolderView {
    readonly path: string | null;
    readonly state: string | null;
    readonly reason: string | null;
    readonly freeBytes: number | null;
}

export interface JobView {
    readonly jobId: string;
    readonly kind: string | null;
    readonly state: string | null;
    readonly phase: string | null;
    readonly doneBytes: number | null;
    readonly totalBytes: number | null;
    readonly filesDone: number | null;
    readonly filesTotal: number | null;
    readonly percent: number | null;
    readonly result: Readonly<Record<string, unknown>> | null;
    readonly error: { readonly code: string; readonly detail: unknown } | null;
    readonly updatedAt: string | null;
}

export interface Summary {
    readonly primary: FolderView | null;
    readonly second: FolderView | null;
    readonly encryptDefault: boolean | null;
    readonly recipients: readonly string[];
    readonly runningJob: JobView | null;
    /* could not be read */
    readonly bundles: number | null;
    readonly backupsAvailable: boolean | null;
}

export interface LocationView {
    readonly where: string;
    readonly verifiedAt: string | null;
    readonly state: string | null;
}

export interface BundleView {
    readonly bundleId: string;
    readonly scope: string | null;
    readonly label: string | null;
    readonly createdAt: string | null;
    readonly verifiedAt: string | null;
    readonly conversations: number | null;
    readonly locations: readonly LocationView[];
    readonly localRemoved: boolean;
    readonly projectRoot: string | null;
}

export interface Blocker {
    readonly code: string;
    readonly detail: string;
}

export interface SkippedFolder {
    readonly path: string;
    readonly bytes: number | null;
}

export interface ProjectFilesView {
    readonly files: number | null;
    readonly bytes: number | null;
    readonly skipped: readonly SkippedFolder[];
    readonly skippedFolders: number | null;
    readonly skippedBytes: number | null;
    readonly specials: readonly string[];
    readonly large: boolean;
    readonly warnBytes: number | null;
}

export interface BackupFamily {
    readonly unit: string;
    readonly plugin: string;
    readonly pluginNameKey: string;
    readonly state: string;
}

export interface BackupFamilies {
    readonly conversations: boolean;
    readonly folders: readonly BackupFamily[];
}

export interface CarriedFamily {
    readonly unit: string;
    readonly points: number | null;
    readonly files: number | null;
    readonly bytes: number | null;
}

export interface PlanView {
    readonly ok: boolean;
    readonly fingerprint: string | null;
    readonly variant: string | null;
    readonly encrypt: boolean | null;
    readonly recipients: readonly string[];
    readonly conversations: number | null;
    readonly files: number | null;
    readonly estimateBytes: number | null;
    readonly excludedCount: number | null;
    readonly folder: string | null;
    readonly blockers: readonly Blocker[];
    readonly warnings: readonly string[];
    readonly projectFiles: ProjectFilesView | null;
    readonly backupFamilies: readonly CarriedFamily[];
}

export interface ExportRequest {
    readonly scope: 'session' | 'project';
    readonly target: string;
    readonly variant: 'own' | 'share';
    readonly encrypt: boolean | null;
    readonly label: string | null;
    readonly includeProjectFiles?: boolean;
    readonly includeBackups?: boolean;
    readonly backupUnits?: readonly string[];
}

export type Raw = Record<string, unknown>;

export function obj(value: unknown): Raw | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Raw) : null;
}

export function str(value: unknown): string | null {
    return typeof value === 'string' ? value : null;
}

export function num(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function bool(value: unknown): boolean | null {
    return typeof value === 'boolean' ? value : null;
}

export function strings(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export function objects(value: unknown): Raw[] {
    return Array.isArray(value) ? value.map(obj).filter((v): v is Raw => v !== null) : [];
}

export function parseFolder(raw: unknown): FolderView | null {
    const o = obj(raw);
    if (!o) return null;
    return { path: str(o.path), state: str(o.state), reason: str(o.reason), freeBytes: num(o.free_bytes) };
}

export function parseJob(raw: unknown): JobView | null {
    const o = obj(raw);
    const jobId = o ? str(o.job_id) : null;
    if (!o || !jobId) return null;
    const error = obj(o.error);
    const code = error ? str(error.code) : null;
    return {
        jobId, kind: str(o.kind), state: str(o.state), phase: str(o.phase), doneBytes: num(o.done_bytes),
        totalBytes: num(o.total_bytes), filesDone: num(o.files_done), filesTotal: num(o.files_total), percent: num(o.percent),
        result: obj(o.result), error: error && code ? { code, detail: error.detail ?? null } : null, updatedAt: str(o.updated_at),
    };
}

export function parseSummary(raw: unknown): Summary {
    const o = obj(raw);
    if (!o) throw new Error('crates did not answer with a summary');
    const folders = obj(o.folders);
    return {
        primary: parseFolder(folders?.primary), second: parseFolder(folders?.second), encryptDefault: bool(o.encrypt_default),
        recipients: strings(o.recipients), runningJob: parseJob(o.running_job), bundles: num(o.bundles),
        backupsAvailable: bool(o.backups_available),
    };
}

export function parseBundle(raw: unknown): BundleView | null {
    const o = obj(raw);
    const bundleId = o ? str(o.bundle_id) : null;
    if (!o || !bundleId) return null;
    const locations = objects(o.locations)
        .map((l) => ({ where: str(l.where), verifiedAt: str(l.verified_at), state: str(l.state) }))
        .filter((l): l is LocationView => l.where !== null);
    return {
        bundleId, scope: str(o.scope), label: str(o.label), createdAt: str(o.created_at), verifiedAt: str(o.verified_at),
        conversations: num(o.conversations), locations, localRemoved: o.local_removed === true,
        projectRoot: str(o.project_root),
    };
}

export function isRemoved(bundle: BundleView): boolean {
    return bundle.localRemoved && !bundle.locations.some((l) => l.state === 'present');
}

export function presentCopies(bundle: BundleView): number {
    return bundle.locations.filter((l) => l.state === 'present').length;
}

export function parseProjectFiles(raw: unknown): ProjectFilesView | null {
    const o = obj(raw);
    if (!o) return null;
    const skipped = objects(o.skipped)
        .map((d) => ({ path: str(d.path), bytes: num(d.bytes) }))
        .filter((d): d is SkippedFolder => d.path !== null);
    return {
        files: num(o.files), bytes: num(o.bytes), skipped, skippedFolders: num(o.skipped_folders), skippedBytes: num(o.skipped_bytes),
        specials: strings(o.specials), large: o.large === true, warnBytes: num(o.warn_bytes),
    };
}

export function parsePlan(raw: unknown): PlanView {
    const o = obj(raw);
    if (!o) throw new Error('crates did not answer with a plan');
    const blockers = objects(o.blockers)
        .map((b) => ({ code: str(b.code), detail: str(b.detail) ?? '' }))
        .filter((b): b is Blocker => b.code !== null);
    return {
        ok: o.ok === true, fingerprint: str(o.fingerprint), variant: str(o.variant), encrypt: bool(o.encrypt),
        recipients: strings(o.recipients), conversations: Array.isArray(o.conversations) ? o.conversations.length : null,
        files: num(o.files), estimateBytes: num(o.estimate_bytes), excludedCount: num(o.excluded_count), folder: str(o.folder),
        blockers, warnings: strings(o.warnings), projectFiles: parseProjectFiles(o.project_files),
        backupFamilies: objects(obj(o.backups)?.families)
            .map((f) => ({ unit: str(f.unit), points: num(f.points), files: num(f.files), bytes: num(f.bytes) }))
            .filter((f): f is CarriedFamily => f.unit !== null),
    };
}

export function parseBackupFamilies(raw: unknown): BackupFamilies {
    const o = obj(raw);
    if (!o) throw new Error('crates did not answer with the backup families');
    const folders = objects(o.folders)
        .map((f) => ({ unit: str(f.unit), plugin: str(f.plugin) ?? '', pluginNameKey: str(f.plugin_name_key) ?? '', state: str(f.state) ?? 'ok' }))
        .filter((f): f is BackupFamily => f.unit !== null);
    return { conversations: obj(o.conversations)?.available === true, folders };
}

function planBody(req: ExportRequest): Raw {
    const body: Raw = { scope: req.scope, target: req.target, variant: req.variant, encrypt: req.encrypt, label: req.label || null };
    if (req.includeProjectFiles) body.include_project_files = true;
    if (req.includeBackups) body.include_backups = true;
    if (req.backupUnits?.length) body.backup_units = [...req.backupUnits];
    return body;
}

export async function fetchBackupFamilies(scope: 'session' | 'project', target: string, fetcher: Fetcher = authFetch): Promise<BackupFamilies> {
    return parseBackupFamilies(await fetcher<unknown>(`${ROUTE}/backup-families`, { method: 'POST', body: JSON.stringify({ scope, target }) }));
}

export async function fetchSummary(fetcher: Fetcher = authFetch): Promise<Summary> {
    return parseSummary(await fetcher<unknown>(`${ROUTE}/summary`));
}

export async function fetchBundles(project: number | null = null, fetcher: Fetcher = authFetch): Promise<BundleView[]> {
    const query = project === null ? '' : `?project=${encodeURIComponent(String(project))}`;
    const answer = obj(await fetcher<unknown>(`${ROUTE}/bundles${query}`));
    return objects(answer?.bundles).map(parseBundle).filter((b): b is BundleView => b !== null);
}

export async function fetchJob(jobId: string, fetcher: Fetcher = authFetch): Promise<JobView> {
    const job = parseJob(await fetcher<unknown>(`${ROUTE}/jobs/${encodeURIComponent(jobId)}`));
    if (!job) throw new Error('crates did not answer with a job');
    return job;
}

export async function previewPlan(req: ExportRequest, fetcher: Fetcher = authFetch): Promise<PlanView> {
    return parsePlan(await fetcher<unknown>(`${ROUTE}/plan`, { method: 'POST', body: JSON.stringify(planBody(req)) }));
}

function jobIdOf(raw: unknown): string {
    const id = str(obj(raw)?.job_id);
    if (!id) throw new Error('crates did not answer with a job id');
    return id;
}

export async function startExport(req: ExportRequest, fingerprint: string, fetcher: Fetcher = authFetch): Promise<string> {
    const body = JSON.stringify({ ...planBody(req), fingerprint });
    return jobIdOf(await fetcher<unknown>(`${ROUTE}/exports`, { method: 'POST', body }));
}

export async function verifyBundle(bundleId: string, level: 'quick' | 'full' = 'full', fetcher: Fetcher = authFetch): Promise<string> {
    const path = `${ROUTE}/bundles/${encodeURIComponent(bundleId)}/verify`;
    return jobIdOf(await fetcher<unknown>(path, { method: 'POST', body: JSON.stringify({ level }) }));
}

export async function copyBundle(bundleId: string, fetcher: Fetcher = authFetch): Promise<string> {
    const path = `${ROUTE}/bundles/${encodeURIComponent(bundleId)}/copies`;
    return jobIdOf(await fetcher<unknown>(path, { method: 'POST', body: JSON.stringify({ folder: 'second' }) }));
}

export async function cancelJob(jobId: string, fetcher: Fetcher = authFetch): Promise<boolean> {
    const answer = obj(await fetcher<unknown>(`${ROUTE}/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }));
    return answer?.cancelled === true;
}

function refusal(error: unknown): Raw | null {
    return error instanceof ApiError ? obj(obj(error.payload)?.detail) : null;
}

export function errorCode(error: unknown): string | null {
    return str(refusal(error)?.code);
}

export function changedPlan(error: unknown): PlanView | null {
    const r = refusal(error);
    return r && r.code === 'plan_changed' && obj(r.detail) ? parsePlan(r.detail) : null;
}

export function codeSentence(code: string, detail: unknown, t: Translate): string {
    const key = `${ERROR_KEY}${code}`;
    const said = t(key);
    if (said !== key) return said;
    return typeof detail === 'string' && detail ? detail : code;
}

export function errorSentence(error: unknown, t: Translate): string {
    const r = refusal(error);
    const code = str(r?.code);
    if (code) return codeSentence(code, r?.detail, t);
    return error instanceof Error ? error.message : String(error);
}

export function unencryptedFindings(job: JobView | null): number {
    const result = job?.state === 'done' && job.kind === 'export' ? job.result : null;
    const count = result && result.variant === 'own' && result.encrypted === false ? result.findings : 0;
    return typeof count === 'number' && Number.isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

export function jobFinished(job: JobView | null): boolean {
    return !!job && job.state !== null && job.state !== 'running';
}

export function bytesText(bytes: number | null): string {
    if (bytes === null) return '';
    const units = ['b', 'kb', 'mb', 'gb', 'tb'];
    let value = bytes;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    return unit === 0 ? `${value} b` : `${value.toFixed(1)} ${units[unit]}`;
}
