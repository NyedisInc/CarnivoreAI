
export function openSidebarLegend(event: MouseEvent): void {
    const help = (window as unknown as { SidebarHelp?: { open(anchor: Element | null): void } }).SidebarHelp;
    help?.open(event.currentTarget as Element | null);
}
