
export interface ThemeRow {
  chip: string;
  line?: string;
}

export interface ThemeTile {
  id: string;
  name: string;
  current: boolean;
  interior: string;
  border: string;
  rows: [ThemeRow, ThemeRow, ThemeRow, ThemeRow, ThemeRow];
}


function rowsOf(id: string): [ThemeRow, ThemeRow, ThemeRow, ThemeRow, ThemeRow] {
  const chip = (n: number) => `--oc-theme-${id}-chip-${n}`;
  const line = (n: number) => `--oc-theme-${id}-line-${n}`;
  return [
    { chip: chip(1), line: line(1) },
    { chip: chip(2), line: line(2) },
    { chip: chip(3), line: line(3) },
    { chip: chip(4) },
    { chip: chip(4) },
  ];
}

function tileOf(id: string, name: string, current = false): ThemeTile {
  return {
    id,
    name,
    current,
    interior: `--oc-theme-${id}-bg`,
    border: `--oc-theme-${id}-border`,
    rows: rowsOf(id),
  };
}

export const themes: ThemeTile[] = [
  tileOf('terminal', 'Terminal', true),
  tileOf('cyber', 'Cyber'),
  tileOf('dracula', 'Dracula'),
  tileOf('nord', 'Nord'),
  tileOf('solarized', 'Solarized'),
  tileOf('light', 'Light'),
];
