import { ApiError, authFetch, type Translate } from '../sdk';
import { bool, num, obj, objects, ROUTE, str, type Fetcher, type Raw } from './crate-api';

export type ImportSource = { readonly bundleId: string } | { readonly folder: 'primary' | 'second'; readonly name: string };

export interface ImportRequest {
    readonly source: ImportSource;
    readonly mode: 'same_paths' | 'relocate';
    readonly newRoot?: string | null;
    readonly skipConflicts?: boolean;
    readonly includeInstructions?: boolean;
    readonly includeProjectFiles?: boolean;
    readonly workInRestoredCopy?: boolean;
    readonly includePluginData?: boolean;
    readonly keepConversations?: boolean;
    readonly fileBackups?: boolean;
    readonly fileBackupUnits?: readonly string[];
    readonly madeHere?: boolean;
    readonly identity?: string | null;
}

export interface Finding {
    readonly code: string;
    readonly detail: string;
}

export interface ImportConversation {
    readonly id: string;
    readonly title: string | null;
    readonly cls: string;
    readonly resume: string;
    readonly reason: string | null;
}

export interface ImportRows {
    readonly table: string;
    readonly insert: number;
    readonly present: number;
    readonly keptLocal: number;
    readonly skipped: number;
    readonly reason: string | null;
}

export interface ImportProject {
    readonly action: string | null;
    readonly name: string | null;
    readonly rootFrom: string | null;
    readonly rootTo: string | null;
    readonly nameChangedTo: string | null;
    readonly suggestedRoot: string | null;
    readonly adoptions: number;
}

export interface ImportCarries {
    readonly projectFiles: boolean;
    readonly workInRestoredCopy: boolean;
    readonly pluginData: boolean;
}

export interface ImportCleanup {
    readonly periodDays: number;
    readonly filesOlder: number;
    readonly oldestDays: number;
    readonly needsGuard: boolean;
    readonly refused: string | null;
}

export interface ImportBackupFolder {
    readonly unit: string;
    readonly plugin: string;
    readonly points: number;
    readonly files: number;
    readonly bytes: number;
    readonly already: number;
    readonly status: string;
    readonly reason: string | null;
}

export interface ImportBackups {
    readonly providerEnabled: boolean | null;
    readonly conversations: readonly { readonly id: string; readonly points: number; readonly files: number; readonly bytes: number;
        readonly already: number; readonly status: string; readonly reason: string | null }[];
    readonly folders: readonly ImportBackupFolder[];
}

export interface ImportProjectFolder {
    readonly path: string;
    /* does not exist yet */
    readonly create: boolean;
    readonly files: string | null;
    readonly side: string | null;
    readonly matching: number | null;
    readonly differing: number | null;
}

export interface ImportPlanView {
    readonly ok: boolean;
    readonly startAvailable: boolean;
    readonly fingerprint: string | null;
    /* could not be read */
    readonly provenance: string | null;
    readonly provenanceReason: string | null;
    readonly crateLabel: string | null;
    readonly carries: ImportCarries | null;
    readonly projectFolder: ImportProjectFolder | null;
    readonly cleanup: ImportCleanup | null;
    readonly backups: ImportBackups | null;
    readonly restamp: boolean;
    readonly project: ImportProject | null;
    readonly mapping: readonly { readonly from: string; readonly to: string }[];
    readonly conversations: readonly ImportConversation[];
    readonly rows: readonly ImportRows[];
    readonly files: number | null;
    readonly bytes: number | null;
    readonly memoryFiles: number | null;
    readonly plans: number | null;
    readonly heldBack: boolean;
    readonly notRestored: readonly { readonly what: string; readonly why: string }[];
    readonly blockers: readonly Finding[];
    readonly warnings: readonly Finding[];
}

function findings(value: unknown): Finding[] {
    return objects(value)
        .map((f) => ({ code: str(f.code), detail: str(f.detail) ?? '' }))
        .filter((f): f is Finding => f.code !== null);
}

function parseProject(raw: unknown): ImportProject | null {
    const o = obj(raw);
    if (!o) return null;
    return {
        action: str(o.action), name: str(o.name), rootFrom: str(o.root_from), rootTo: str(o.root_to),
        nameChangedTo: str(o.name_changed_to), suggestedRoot: str(o.suggested_root),
        adoptions: Array.isArray(o.adoptions) ? o.adoptions.length : 0,
    };
}

function parseCarries(raw: unknown): ImportCarries | null {
    const o = obj(raw);
    return !o ? null : { projectFiles: o?.project_files === true, workInRestoredCopy: o?.work_in_restored_copy === true, pluginData: o?.plugin_data === true };
}

function parseCleanup(raw: unknown): ImportCleanup | null {
    const o = obj(raw);
    return o && num(o.period_days) !== null ? { periodDays: num(o.period_days) ?? 30, filesOlder: num(o.files_older) ?? 0, oldestDays: num(o.oldest_days) ?? 0,
        needsGuard: o.needs_guard === true, refused: str(o.refused) } : null;
}

function parseBackups(raw: unknown): ImportBackups | null {
    const o = obj(raw);
    const rows = objects(o?.conversations).flatMap((c) => (str(c.id) ? [{ id: str(c.id)!, points: num(c.points) ?? 0, files: num(c.files) ?? 0,
        bytes: num(c.bytes) ?? 0, already: num(c.already) ?? 0, status: str(c.status) ?? 'restore', reason: str(c.reason) }] : []));
    const folders = objects(o?.folders).flatMap((c) => (str(c.unit) ? [{ unit: str(c.unit)!, plugin: str(c.plugin) ?? str(c.unit)!.split('.')[0]!,
        points: num(c.points) ?? 0, files: num(c.files) ?? 0, bytes: num(c.bytes) ?? 0, already: num(c.already) ?? 0,
        status: str(c.status) ?? 'restore', reason: str(c.reason) }] : []));
    return o && o.carried === true && (rows.length || folders.length) ? { providerEnabled: bool(o.provider_enabled), conversations: rows, folders } : null;
}

function parseProjectFolder(raw: unknown, sideFolder: unknown): ImportProjectFolder | null {
    const o = obj(raw);
    const path = str(o?.path);
    const side = obj(sideFolder);
    return o && path ? { path, create: o.create === true, files: str(o.files), side: str(o.side), matching: num(side?.matching), differing: num(side?.differing) } : null;
}

export function parseImportPlan(raw: unknown): ImportPlanView {
    const o = obj(raw);
    if (!o) throw new Error('crates did not answer with an import plan');
    const rowsBlock = obj(o.rows) ?? {};
    const rows = Object.entries(rowsBlock).flatMap(([table, value]) => {
        const r = obj(value);
        return r ? [{ table, insert: num(r.insert) ?? 0, present: num(r.present) ?? 0, keptLocal: num(r.kept_local) ?? 0,
            skipped: num(r.skipped) ?? 0, reason: str(r.reason) }] : [];
    });
    const files = obj(o.files);
    const instructions = obj(o.instructions);
    return {
        ok: o.ok === true, startAvailable: o.start_available === true, fingerprint: str(o.fingerprint) || null, provenance: str(o.provenance), provenanceReason: str(o.provenance_reason),
        crateLabel: str(obj(o.crate)?.label), carries: parseCarries(o.carries), projectFolder: parseProjectFolder(o.project_folder, obj(o.files)?.side_folder), project: parseProject(o.project), cleanup: parseCleanup(o.cleanup), backups: parseBackups(o.backups), restamp: files?.restamp === true,
        mapping: objects(o.mapping).flatMap((m) => (str(m.from) && str(m.to) ? [{ from: str(m.from)!, to: str(m.to)! }] : [])),
        conversations: objects(o.conversations).flatMap((c) => (str(c.id) ? [{ id: str(c.id)!, title: str(c.title), cls: str(c.class) ?? 'write',
            resume: str(c.resume) ?? 'file_only', reason: str(c.reason) }] : [])),
        rows, files: num(files?.count), bytes: num(files?.bytes), memoryFiles: num(instructions?.memory_files), plans: num(instructions?.plans),
        heldBack: bool(instructions?.held_back) === true,
        notRestored: objects(o.not_restored).flatMap((n) => (str(n.what) ? [{ what: str(n.what)!, why: str(n.why) ?? '' }] : [])),
        blockers: findings(o.blockers), warnings: findings(o.warnings),
    };
}

export function importBody(req: ImportRequest): Raw {
    const source = 'bundleId' in req.source ? { bundle_id: req.source.bundleId } : { folder: req.source.folder, name: req.source.name };
    const body: Raw = { source, mode: req.mode };
    if (req.newRoot) body.new_root = req.newRoot;
    if (req.skipConflicts) body.skip_conflicts = true;
    if (req.includeInstructions) body.include_instructions = true;
    if (req.includeProjectFiles) body.include_project_files = true;
    if (req.workInRestoredCopy) body.work_in_restored_copy = true;
    if (req.includePluginData) body.include_plugin_data = true;
    if (req.keepConversations) body.keep_conversations = true;
    if (req.fileBackups) body.file_backups = true;
    if (req.fileBackupUnits?.length) body.file_backup_units = [...req.fileBackupUnits];
    if (req.madeHere) body.made_here = true;
    if (req.identity) body.identity = req.identity;
    return body;
}

export async function previewImport(req: ImportRequest, fetcher: Fetcher = authFetch): Promise<ImportPlanView> {
    return parseImportPlan(await fetcher<unknown>(`${ROUTE}/imports/plan`, { method: 'POST', body: JSON.stringify(importBody(req)) }));
}

export async function startImport(req: ImportRequest, fingerprint: string, fetcher: Fetcher = authFetch): Promise<string> {
    const answer = obj(await fetcher<unknown>(`${ROUTE}/imports`, { method: 'POST', body: JSON.stringify({ ...importBody(req), fingerprint }) }));
    const id = str(answer?.job_id);
    if (!id) throw new Error('crates did not answer with a job id');
    return id;
}

function sentence(prefix: string, finding: Finding, t: Translate): string {
    const key = `${prefix}${finding.code}`;
    const said = t(key);
    return said !== key ? said : finding.detail || finding.code;
}

export function blockerSentence(finding: Finding, t: Translate): string {
    return sentence('cplug.crate.import.error.', finding, t);
}

export function warningSentence(finding: Finding, t: Translate): string {
    return sentence('cplug.crate.import.warning.', finding, t);
}

export function provenanceSentence(reason: string | null, t: Translate): string {
    if (!reason) return '';
    const key = `cplug.crate.import.provenance.${reason}`;
    const said = t(key);
    return said !== key ? said : reason;
}

export function skipSentence(reason: string, t: Translate, kept = false): string {
    for (const scope of kept ? ['skip_kept', 'skip'] : ['skip']) {
        const key = `cplug.crate.import.${scope}.${reason}`;
        const said = t(key);
        if (said !== key) return said;
    }
    return reason;
}

export function keptSubject(what: string, t: Translate): string {
    const m = /^files:([a-z_]+) \((\d+)\)$/.exec(what);
    if (!m) return what;
    const key = `cplug.crate.import.role.${m[1]}`;
    const said = t(key, { count: Number(m[2]) });
    return said !== key ? said : what;
}

export function hasConflicts(plan: ImportPlanView | null): boolean {
    return !!plan && (plan.conversations.some((c) => c.cls === 'conflict') || plan.blockers.some((b) => b.code === 'conflict' || b.code === 'conversation_owned_elsewhere'));
}

export function changedImportPlan(error: unknown): ImportPlanView | null {
    const detail = error instanceof ApiError ? obj(obj(error.payload)?.detail) : null;
    return detail && detail.code === 'plan_changed' && obj(detail.detail) ? parseImportPlan(detail.detail) : null;
}
