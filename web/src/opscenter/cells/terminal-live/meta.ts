
export const TOOLS_MENU_IS_PAGE_CHROME = true;

export function drivesItsOwnSession(page: string): boolean {
  return page === 'terminal';
}
