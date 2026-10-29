interface DrawerOpener {
  isOpen?: boolean;
  open?(opts?: { persist?: boolean }): void;
}

export function showDrawerForPage(): void {
  const drawer = (globalThis as { SessionSidebar?: DrawerOpener }).SessionSidebar;
  if (drawer && !drawer.isOpen) drawer.open?.({ persist: false });
}
