
import declarations from '../../../../src/data/widgets.json';
import { CELL_IDS, INSTANCE_KINDS } from '../engine/meta';
import type { CellId, InstanceKind } from '../engine/types';
import { isGridSizeName, type GridSizeName } from './named-sizes';
import { MAX_PER_SURFACE_CEILING } from './types';

const FITS_KEYS: readonly string[] = ['sizes', 'anySize', 'max_per_surface'];


const RETIRED_KEYS: Readonly<Record<string, string>> = Object.freeze({
  zones: 'every widget goes everywhere',
  suggested: 'renamed fits.sizes: the named sizes a widget supports',
  tested: 'renamed fits.sizes: sizes are called out by name',
  allowed: 'declare fits.sizes, by name',
  max: 'there is no ceiling, declare fits.sizes',
});

export interface FitDeclaration {
  sizes: readonly GridSizeName[];
  anySize: boolean;
  max_per_surface?: number;
}

export interface DeclaredRow {
  id: string;
  instancing?: string;
  fits?: Record<string, unknown>;
}

export class FitDeclarationError extends Error {}

export function declarationOf(key: CellId | InstanceKind, rows: readonly DeclaredRow[]): FitDeclaration {
  const id = `core.${key}`;
  const row = rows.find((one) => one.id === id);
  if (!row) throw new FitDeclarationError(`${id} has no row in src/data/widgets.json`);
  return declarationFromRow(row);
}

export function declarationFromRow(row: DeclaredRow): FitDeclaration {
  const id = row.id;
  const fits = row.fits;
  if (fits === undefined) throw new FitDeclarationError(`${id} declares no fits: call out its sizes by name (fits.sizes)`);
  for (const name of Object.keys(fits)) {
    if (RETIRED_KEYS[name]) throw new FitDeclarationError(`${id} fits.${name} is retired: ${RETIRED_KEYS[name]}`);
    if (!FITS_KEYS.includes(name)) throw new FitDeclarationError(`${id} fits carries unknown key ${name}`);
  }
  const sizes = fits.sizes;
  if (!Array.isArray(sizes) || sizes.length === 0) throw new FitDeclarationError(`${id} fits.sizes is not a list of size names`);
  for (const [index, one] of sizes.entries()) {
    if (!isGridSizeName(one)) throw new FitDeclarationError(`${id} fits.sizes[${index}] is not a size name: ${String(one)}`);
  }
  if (new Set(sizes).size !== sizes.length) throw new FitDeclarationError(`${id} fits.sizes repeats a name`);
  const anySize = fits.anySize ?? false;
  if (typeof anySize !== 'boolean') throw new FitDeclarationError(`${id} fits.anySize is not true or false`);
  const limit = fits.max_per_surface;
  if (limit !== undefined) {
    if (typeof limit !== 'number' || !Number.isInteger(limit) || limit < 1 || limit > MAX_PER_SURFACE_CEILING) {
      throw new FitDeclarationError(`${id} fits.max_per_surface must be a whole number from 1 to ${MAX_PER_SURFACE_CEILING}`);
    }
    if (row.instancing === 'singleton' && limit !== 1) {
      throw new FitDeclarationError(`${id} is a singleton, so fits.max_per_surface can only be 1`);
    }
  }
  return Object.freeze({
    sizes: Object.freeze([...(sizes as GridSizeName[])]),
    anySize,
    ...(limit === undefined ? {} : { max_per_surface: limit }),
  });
}

const PLUGIN_DECLARATIONS = new Map<string, FitDeclaration>();

export function registerPluginDeclaration(row: DeclaredRow): void {
  PLUGIN_DECLARATIONS.set(row.id, declarationFromRow(row));
}

export function pluginDeclarationFor(key: string): FitDeclaration | undefined {
  return PLUGIN_DECLARATIONS.get(key);
}

const ROWS: readonly DeclaredRow[] = (declarations as { widgets: DeclaredRow[] }).widgets;

export const FIT_DECLARATIONS: Readonly<Record<CellId | InstanceKind, FitDeclaration>> = Object.freeze(
  Object.fromEntries([...CELL_IDS, ...INSTANCE_KINDS].map((key) => [key, declarationOf(key, ROWS)])) as Record<
    CellId | InstanceKind,
    FitDeclaration
  >,
);
