
export interface LegendItem { name: string; color: string; on: boolean;  id?: string }

export function legendPages(widths: readonly number[], roomPx: number, gapPx: number): number[] {
  const starts: number[] = [];
  let used = 0;
  widths.forEach((width, at) => {
    const next = used === 0 ? width : used + gapPx + width;
    if (starts.length === 0 || next > roomPx) {
      starts.push(at);
      used = width;
    } else used = next;
  });
  return starts;
}

export function legendFitsOneRow(widths: readonly number[], roomPx: number, gapPx: number): boolean {
  return widths.reduce((sum, width, at) => sum + width + (at === 0 ? 0 : gapPx), 0) <= roomPx;
}
