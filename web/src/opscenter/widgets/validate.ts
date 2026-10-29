
import { GRID_SIZE_NAMES, NAMED_SIZE_UNITS, isGridSizeName, type GridSizeName } from './named-sizes';
import {
  LOOK_SURFACES,
  MAX_PER_SURFACE_CEILING,
  WIDGET_CANVASES,
  WIDGET_CAPABILITIES,
  WIDGET_CATEGORIES,
  WIDGET_INSTANCINGS,
  WIDGET_LOOKS,
  WIDGET_TYPES,
  type ManifestCheck,
  type ManifestRefusal,
  type WidgetManifest,
} from './types';

const ID_PATTERN = /^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)+$/;
const SEMVER_PATTERN = /^\d+\.\d+\.\d+$/;
const TIER_NAME_PATTERN = /^[a-z][a-z0-9-]*$/;
const SETTING_KEY_PATTERN = /^[a-z][a-zA-Z0-9]*$/;
const CATALOG_KEY_PATTERN = /^[a-z0-9_]+(\.[a-z0-9_-]+)+$/;
const KNOWN_FIELDS: ReadonlySet<string> = new Set([
  'id',
  'version',
  'titleKey',
  'icon',
  'iconTone',
  'category',
  'type',
  'instancing',
  'canvases',
  'looks',
  'bounds',
  'fits',
  'densities',
  'settings',
  'capabilities',
  'keepAlive',
  'scope',
  'views',
  'viewOf',
  'remembers',
]);

class ManifestRefused extends Error {
  constructor(
    readonly refusal: ManifestRefusal,
    detail: string,
  ) {
    super(detail);
  }
}

function need(ok: boolean, refusal: ManifestRefusal, detail: string): asserts ok {
  if (!ok) throw new ManifestRefused(refusal, detail);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isSize(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function checkClosedList(
  value: unknown,
  known: readonly string[],
  refusal: ManifestRefusal,
  label: string,
  allowEmpty: boolean,
): void {
  need(Array.isArray(value), refusal, `${label} must be a list`);
  need(allowEmpty || value.length > 0, refusal, `${label} must not be empty`);
  const seen = new Set<string>();
  for (const entry of value) {
    need(typeof entry === 'string' && known.includes(entry), refusal, `${label} names an unknown value: ${String(entry)}`);
    need(!seen.has(entry), refusal, `${label} repeats ${entry}`);
    seen.add(entry);
  }
}

function checkViews(value: unknown, ownId: string): void {
  if (value === undefined) return;
  need(Array.isArray(value) && value.length >= 2, 'views', 'views must list at least two views');
  const seen = new Set<string>();
  for (const view of value as unknown[]) {
    need(isRecord(view), 'views', 'a view must be an object');
    need(typeof view.id === 'string' && TIER_NAME_PATTERN.test(view.id) && !seen.has(view.id), 'views', `view id must be flat lowercase and unique: ${String(view.id)}`);
    seen.add(view.id as string);
    need(typeof view.titleKey === 'string' && CATALOG_KEY_PATTERN.test(view.titleKey), 'views', 'a view titleKey must be a catalog key');
    need(typeof view.widget === 'string' && ID_PATTERN.test(view.widget), 'views', 'a view widget must be a widget id');
  }
  need((value as { widget: string }[])[0]?.widget === ownId, 'views', 'the first view must be drawn by the widget itself');
}

function checkLooks(value: unknown): void {
  if (value === undefined) return;
  need(isRecord(value), 'looks', 'looks must be an object');
  checkClosedList(value.names, WIDGET_LOOKS, 'looks', 'looks.names', false);
  need(isRecord(value.defaults), 'looks', 'looks.defaults must be an object');
  for (const [surface, look] of Object.entries(value.defaults)) {
    need(LOOK_SURFACES.includes(surface), 'looks', `looks.defaults names an unknown surface: ${surface}`);
    need(
      typeof look === 'string' && (value.names as string[]).includes(look),
      'looks',
      `looks.defaults.${surface} is not one of looks.names`,
    );
  }
}

function checkBounds(value: unknown): void {
  need(isRecord(value), 'bounds', 'bounds must be an object');
  need(isSize(value.minW) && isSize(value.minH), 'bounds', 'bounds.minW and bounds.minH must be sizes');
  for (const [max, min] of [
    ['maxW', 'minW'],
    ['maxH', 'minH'],
  ] as const) {
    if (value[max] === undefined) continue;
    need(isSize(value[max]), 'bounds', `bounds.${max} must be a size`);
    need((value[max] as number) >= (value[min] as number), 'bounds', `bounds.${max} is below bounds.${min}`);
  }
}

const MAX_FIT_UNITS = 256;

function isFitSize(value: unknown): boolean {
  return (
    isRecord(value) &&
    Object.keys(value).every((key) => key === 'w' || key === 'h') &&
    [value.w, value.h].every((n) => typeof n === 'number' && Number.isInteger(n) && n >= 1 && n <= MAX_FIT_UNITS)
  );
}

function checkFits(value: unknown, singleton: boolean): void {
  need(isRecord(value), 'fits', 'fits must be an object: every widget declares its floor and the sizes it supports, by name');
  for (const retired of ['zones', 'suggested', 'tested', 'max', 'allowed']) {
    need(!(retired in value), 'fits', `fits.${retired} is retired: call out sizes by name in fits.sizes (docs/widget-spec.md section 10)`);
  }
  need(isFitSize(value.min), 'fits', 'fits.min must be {w, h} in whole grid units');
  const min = value.min as { w: number; h: number };
  need(typeof value.anySize === 'boolean', 'fits', 'fits.anySize must be true or false');
  need(Array.isArray(value.sizes) && value.sizes.length > 0, 'fits', 'fits.sizes must name at least one size');
  const seen = new Set<string>();
  for (const name of value.sizes as unknown[]) {
    need(isGridSizeName(name), 'fits', `fits.sizes holds ${String(name)}, which is not a size name (${GRID_SIZE_NAMES.join(', ')})`);
    const units = NAMED_SIZE_UNITS[name as GridSizeName];
    need(units.w >= min.w && units.h >= min.h, 'fits', `fits.sizes ${String(name)} is below the floor`);
    need(!seen.has(name as string), 'fits', `fits.sizes repeats ${String(name)}`);
    seen.add(name as string);
  }
  if (value.max_per_surface !== undefined) {
    const limit = value.max_per_surface;
    need(
      typeof limit === 'number' && Number.isInteger(limit) && limit >= 1 && limit <= MAX_PER_SURFACE_CEILING,
      'fits',
      `fits.max_per_surface must be a whole number from 1 to ${MAX_PER_SURFACE_CEILING}`,
    );
    need(!(singleton && limit !== 1), 'fits', 'a singleton is one panel per page, so fits.max_per_surface can only be 1');
  }
}

function checkLadder(value: unknown, axis: string, ceiling: unknown): void {
  need(Array.isArray(value) && value.length > 0, 'densities', `densities.${axis} must be a non-empty list`);
  const names = new Set<string>();
  let last = -1;
  for (const tier of value) {
    need(isRecord(tier), 'densities', `densities.${axis} holds a step that is not an object`);
    const { name, min } = tier;
    need(typeof name === 'string' && TIER_NAME_PATTERN.test(name), 'densities', `densities.${axis} has a bad step name: ${String(name)}`);
    need(!names.has(name), 'densities', `densities.${axis} repeats step ${name}`);
    need(isSize(min), 'densities', `densities.${axis} step ${name} has no size`);
    need(min > last, 'densities', `densities.${axis} step ${name} does not rise above the step before it`);
    need(ceiling === undefined || min <= (ceiling as number), 'densities', `densities.${axis} step ${name} starts above the widget's maximum`);
    names.add(name);
    last = min;
  }
}

function checkSettingField(key: string, field: unknown): void {
  const where = `settings.fields.${key}`;
  need(SETTING_KEY_PATTERN.test(key), 'settings', `${where}: key must be camelCase letters and digits`);
  need(isRecord(field), 'settings', `${where} must be an object`);
  need(typeof field.labelKey === 'string' && CATALOG_KEY_PATTERN.test(field.labelKey), 'settings', `${where}.labelKey must be a catalog key`);
  need(field.hintKey === undefined || (typeof field.hintKey === 'string' && CATALOG_KEY_PATTERN.test(field.hintKey)), 'settings', `${where}.hintKey must be a catalog key`);
  need(field.keywordsKey === undefined || (typeof field.keywordsKey === 'string' && CATALOG_KEY_PATTERN.test(field.keywordsKey)), 'settings', `${where}.keywordsKey must be a catalog key`);
  need(field.control === undefined || (field.kind === 'enum' && (field.control === 'segmented' || field.control === 'select')), 'settings', `${where}.control is not segmented or select on an enum`);
  switch (field.kind) {
    case 'boolean':
      need(typeof field.default === 'boolean', 'settings', `${where}.default must be true or false`);
      return;
    case 'number': {
      const { default: value, min, max } = field;
      need(typeof value === 'number' && Number.isFinite(value), 'settings', `${where}.default must be a number`);
      need(min === undefined || (typeof min === 'number' && value >= min), 'settings', `${where}.default is below its min`);
      need(max === undefined || (typeof max === 'number' && value <= max), 'settings', `${where}.default is above its max`);
      return;
    }
    case 'enum': {
      const { options, default: value } = field;
      need(Array.isArray(options) && options.length > 0 && options.every((o) => typeof o === 'string'), 'settings', `${where}.options must be a non-empty list of words`);
      need(new Set(options).size === options.length, 'settings', `${where}.options repeats a value`);
      need(typeof value === 'string' && options.includes(value), 'settings', `${where}.default is not one of its options`);
      return;
    }
    case 'string': {
      const { default: value, maxLength } = field;
      need(typeof maxLength === 'number' && Number.isInteger(maxLength) && maxLength > 0, 'settings', `${where}.maxLength must be a positive whole number`);
      need(typeof value === 'string' && value.length <= maxLength, 'settings', `${where}.default must be text within maxLength`);
      return;
    }
    default:
      need(false, 'settings', `${where}.kind is not boolean, number, enum or string`);
  }
}

function checkSettings(value: unknown): void {
  if (value === undefined) return;
  need(isRecord(value), 'settings', 'settings must be an object');
  need(typeof value.version === 'number' && Number.isInteger(value.version) && value.version >= 1, 'settings', 'settings.version must be a whole number from 1');
  need(isRecord(value.fields), 'settings', 'settings.fields must be an object');
  for (const [key, field] of Object.entries(value.fields)) checkSettingField(key, field);
  if (value.groups !== undefined) checkSettingGroups(value.groups, value.fields);
}

function checkSettingGroups(groups: unknown, declared: Record<string, unknown>): void {
  const keys = Object.keys(declared);
  need(Array.isArray(groups) && groups.length > 0, 'settings', 'settings.groups must be a non-empty list');
  const seen: string[] = [];
  for (const [at, group] of (groups as unknown[]).entries()) {
    need(isRecord(group) && typeof group.labelKey === 'string' && CATALOG_KEY_PATTERN.test(group.labelKey), 'settings', `settings.groups[${at}].labelKey must be a catalog key`);
    const fields = (group as { fields?: unknown }).fields;
    need(Array.isArray(fields) && fields.length > 0 && fields.every((key) => typeof key === 'string' && keys.includes(key)), 'settings', `settings.groups[${at}].fields must list declared fields`);
    seen.push(...(fields as string[]));
    const matrix = (group as { matrix?: unknown }).matrix;
    if (matrix !== undefined) checkSettingMatrix(matrix, fields as string[], declared, `settings.groups[${at}].matrix`);
  }
  need(seen.length === keys.length && new Set(seen).size === keys.length, 'settings', 'settings.groups must name every field exactly once');
}

function checkSettingMatrix(matrix: unknown, groupKeys: readonly string[], declared: Record<string, unknown>, where: string): void {
  need(isRecord(matrix) && Object.keys(matrix).sort().join(',') === 'columns,rows', 'settings', `${where} must be an object with columns and rows only`);
  const { columns, rows } = matrix as { columns: unknown; rows: unknown };
  need(Array.isArray(columns) && columns.length >= 2 && columns.every((c) => typeof c === 'string' && CATALOG_KEY_PATTERN.test(c)), 'settings', `${where}.columns must be at least two catalog keys`);
  need(Array.isArray(rows) && rows.length > 0, 'settings', `${where}.rows must be a non-empty list`);
  const cells: string[] = [];
  for (const [n, row] of (rows as unknown[]).entries()) {
    const here = `${where}.rows[${n}]`;
    need(isRecord(row) && typeof row.labelKey === 'string' && CATALOG_KEY_PATTERN.test(row.labelKey), 'settings', `${here}.labelKey must be a catalog key`);
    const r = row as Record<string, unknown>;
    need(r.hintKey === undefined || (typeof r.hintKey === 'string' && CATALOG_KEY_PATTERN.test(r.hintKey)), 'settings', `${here}.hintKey must be a catalog key`);
    const locked = r.locked === true;
    const allowed = locked ? ['hintKey', 'labelKey', 'locked'] : ['confirm', 'fields', 'hintKey', 'labelKey'];
    need(Object.keys(r).every((k) => allowed.includes(k)) && (r.locked === undefined || locked), 'settings', `${here} is a locked row or a row of cells`);
    if (locked) continue;
    const own = r.fields;
    need(Array.isArray(own) && own.length === (columns as unknown[]).length
      && own.every((k) => typeof k === 'string' && groupKeys.includes(k) && (declared[k] as { kind?: unknown } | undefined)?.kind === 'boolean'),
      'settings', `${here}.fields must name one boolean field of this group per column`);
    cells.push(...(own as string[]));
    const confirm = r.confirm;
    need(confirm === undefined || (isRecord(confirm) && Object.keys(confirm).length > 0
      && Object.entries(confirm).every(([k, v]) => (own as string[]).includes(k) && typeof v === 'string' && CATALOG_KEY_PATTERN.test(v))),
      'settings', `${here}.confirm must map cells of this row to catalog keys`);
  }
  need(cells.length === groupKeys.length && cells.every((k, i) => k === groupKeys[i]), 'settings', `${where}.rows must name the group's fields exactly once, in order`);
}

function checkAll(value: unknown): WidgetManifest {
  need(isRecord(value), 'not-an-object', 'a manifest must be an object');
  const unknown = Object.keys(value).find((key) => !KNOWN_FIELDS.has(key));
  need(unknown === undefined, 'unknown-field', `unknown field: ${unknown}`);
  need(typeof value.id === 'string' && ID_PATTERN.test(value.id), 'id', `id must be namespaced, like core.notes: ${String(value.id)}`);
  need(typeof value.version === 'string' && SEMVER_PATTERN.test(value.version), 'version', 'version must be major.minor.patch');
  need(typeof value.titleKey === 'string' && CATALOG_KEY_PATTERN.test(value.titleKey), 'title-key', 'titleKey must be a catalog key');
  need(typeof value.icon === 'string' && value.icon.length > 0, 'icon', 'icon must name an icon');
  need(typeof value.iconTone === 'string' && /^oc-[a-z0-9-]+$/.test(value.iconTone), 'icon-tone', 'iconTone must be an --oc-* token name');
  need(typeof value.category === 'string' && (WIDGET_CATEGORIES as readonly string[]).includes(value.category), 'category', `unknown category: ${String(value.category)}`);
  need(typeof value.type === 'string' && (WIDGET_TYPES as readonly string[]).includes(value.type), 'type', `unknown type: ${String(value.type)}`);
  need(typeof value.instancing === 'string' && (WIDGET_INSTANCINGS as readonly string[]).includes(value.instancing), 'instancing', `unknown instancing: ${String(value.instancing)}`);
  checkClosedList(value.canvases, WIDGET_CANVASES, 'canvases', 'canvases', false);
  checkLooks(value.looks);
  checkBounds(value.bounds);
  checkFits(value.fits, value.instancing === 'singleton');
  const bounds = value.bounds as Record<string, unknown>;
  need(isRecord(value.densities), 'densities', 'densities must be an object with width and height');
  checkLadder(value.densities.width, 'width', bounds.maxW);
  checkLadder(value.densities.height, 'height', bounds.maxH);
  checkSettings(value.settings);
  checkClosedList(value.capabilities, WIDGET_CAPABILITIES, 'capabilities', 'capabilities', true);
  need(value.keepAlive === undefined || value.keepAlive === 'host', 'keep-alive', 'keepAlive must be absent or host');
  need(value.scope === undefined || value.scope === 'session', 'scope', 'scope must be absent or session');
  checkViews(value.views, value.id as string);
  need(value.remembers === undefined || (Array.isArray(value.remembers) && value.remembers.every((n) => typeof n === 'string' && /^[a-z][a-z0-9-]{0,47}$/.test(n))), 'remembers', 'remembers must be flat lowercase names');
  need(value.viewOf === undefined || (typeof value.viewOf === 'string' && ID_PATTERN.test(value.viewOf)), 'view-of', 'viewOf must be a widget id');
  return value as unknown as WidgetManifest;
}

export function validateManifest(value: unknown): ManifestCheck {
  try {
    return { ok: true, manifest: checkAll(value) };
  } catch (error) {
    if (error instanceof ManifestRefused) return { ok: false, refusal: error.refusal, detail: error.message };
    throw error;
  }
}
