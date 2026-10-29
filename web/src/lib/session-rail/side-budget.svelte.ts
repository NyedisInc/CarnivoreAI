
export type SideBar = 'drawer' | 'slideout';

class SideBudget {
  #held = $state<Record<SideBar, number>>({ drawer: 0, slideout: 0 });

  hold(bar: SideBar, px: number): void {
    this.#held[bar] = Number.isFinite(px) && px > 0 ? px : 0;
  }

  otherThan(bar: SideBar): number {
    return this.#held[bar === 'drawer' ? 'slideout' : 'drawer'];
  }

  reset(): void {
    this.#held = { drawer: 0, slideout: 0 };
  }
}

export const sideBudget = new SideBudget();
