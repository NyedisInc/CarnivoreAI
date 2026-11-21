
export interface TaskManagerFold {
  action: 'fold' | 'unfold' | 'close';
  items: number[];
  groups: number[];
  project: string | null;
}

export interface TaskManagerView {
  scrollTop(list: string | null): Promise<void>;
  fold(command: TaskManagerFold): Promise<void>;
}

let view: TaskManagerView | null = null;

export function registerTaskManagerView(v: TaskManagerView): void {
  view = v;
}

export function taskManagerView(): TaskManagerView | null {
  return view;
}
