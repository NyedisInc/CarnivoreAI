
function holdCounter(cls: string): (doc: Document) => () => void {
  const counts = new WeakMap<Document, number>();
  return (doc) => {
    if (!doc.body.classList.contains(cls)) counts.set(doc, 0);
    counts.set(doc, (counts.get(doc) ?? 0) + 1);
    doc.body.classList.add(cls);
    let held = true;
    return () => {
      if (!held) return;
      held = false;
      const n = (counts.get(doc) ?? 1) - 1;
      counts.set(doc, Math.max(n, 0));
      if (n <= 0) doc.body.classList.remove(cls);
    };
  };
}

export const acquireDragHold: (doc: Document) => () => void = holdCounter('grid-dragging');

export const acquireCarryHold: (doc: Document) => () => void = holdCounter('grid-carrying');
