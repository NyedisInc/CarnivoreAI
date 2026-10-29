/*  hidden  */
import type { Floor, FloorItem } from './floor';

export interface TreeNode {
  item: FloorItem;
  parent: string | null;
  children: string[];
  depth: number;
}

export interface SwarmTree {
  nodes: Map<string, TreeNode>;
  roots: string[];
  order: string[];
}

export function floorItems(floor: Floor): FloorItem[] {
  return [...(floor.alpha ? [floor.alpha] : []), ...floor.companies, ...floor.projects, ...floor.agents];
}

export function buildTree(floor: Floor): SwarmTree {
  const items = floorItems(floor);
  const byKey = new Map(items.map((i) => [i.key, i] as const));
  const projectKey = new Map<number, string>();
  const companyKey = new Map<number, string>();
  for (const i of floor.projects) if (i.projectId !== null) projectKey.set(i.projectId, i.key);
  for (const i of floor.companies) if (i.companyId !== null) companyKey.set(i.companyId, i.key);
  const alpha = floor.alpha?.key ?? null;

  const wanted = (i: FloorItem): string | null => {
    if (i.section === 'alpha') return null;
    if (i.section === 'companies') return alpha;
    if (i.section === 'projects') return (i.companyId !== null ? companyKey.get(i.companyId) : undefined) ?? alpha;
    const parentAgent = i.agent?.parent_id != null && !i.ordinary ? `agent:${i.agent.parent_id}` : null;
    if (parentAgent && parentAgent !== i.key && byKey.has(parentAgent)) return parentAgent;
    const project = i.projectId !== null ? projectKey.get(i.projectId) : undefined;
    if (project && project !== i.key) return project;
    return (i.companyId !== null ? companyKey.get(i.companyId) : undefined) ?? alpha;
  };

  const nodes = new Map<string, TreeNode>();
  for (const i of items) nodes.set(i.key, { item: i, parent: null, children: [], depth: 0 });
  const under = (key: string, ancestor: string): boolean => {
    for (let at: string | null = key, hops = 0; at !== null && hops <= items.length; hops += 1) {
      if (at === ancestor) return true;
      at = nodes.get(at)?.parent ?? null;
    }
    return false;
  };
  for (const i of items) {
    const want = wanted(i);
    if (want && !under(want, i.key)) {
      (nodes.get(i.key) as TreeNode).parent = want;
      (nodes.get(want) as TreeNode).children.push(i.key);
    }
  }
  const roots = items.filter((i) => nodes.get(i.key)?.parent === null).map((i) => i.key);
  const order: string[] = [];
  const walk = (key: string, depth: number): void => {
    const node = nodes.get(key) as TreeNode;
    node.depth = depth;
    order.push(key);
    for (const child of node.children) walk(child, depth + 1);
  };
  for (const root of roots) walk(root, 0);
  return { nodes, roots, order };
}

export function ledgerRows(tree: SwarmTree, collapsed: ReadonlySet<string>): TreeNode[] {
  const rows: TreeNode[] = [];
  const walk = (key: string): void => {
    const node = tree.nodes.get(key) as TreeNode;
    rows.push(node);
    if (!collapsed.has(key)) for (const child of node.children) walk(child);
  };
  for (const root of tree.roots) walk(root);
  return rows;
}
