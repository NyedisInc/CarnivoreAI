import declarations from '../../../../src/data/widgets.json';

export const GLANCE_HEIGHT_MIN_PX = 24;
export const GLANCE_HEIGHT_MAX_PX = 160;

export class GlanceDeclarationError extends Error {}

interface DeclaredRow {
  id: string;
  glance?: unknown;
}

export function glanceHeightOf(row: DeclaredRow): number | null {
  if (row.glance === undefined) return null;
  const glance = row.glance as { height?: unknown } | null;
  const height = glance?.height;
  if (
    !glance ||
    Object.keys(glance).length !== 1 ||
    typeof height !== 'number' ||
    !Number.isInteger(height) ||
    height < GLANCE_HEIGHT_MIN_PX ||
    height > GLANCE_HEIGHT_MAX_PX
  ) {
    throw new GlanceDeclarationError(`${row.id} glance must be { height: ${GLANCE_HEIGHT_MIN_PX}..${GLANCE_HEIGHT_MAX_PX} px }`);
  }
  return height;
}

const ROWS: readonly DeclaredRow[] = (declarations as { widgets: DeclaredRow[] }).widgets;

export function declaredGlanceHeight(widget: string, rows: readonly DeclaredRow[] = ROWS): number | null {
  const row = rows.find((one) => one.id === widget);
  return row ? glanceHeightOf(row) : null;
}
