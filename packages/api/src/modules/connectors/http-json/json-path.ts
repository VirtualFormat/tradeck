/**
 * Minimal JSONPath: dot access + numeric array index, e.g. "$.data.last",
 * "$.items[0].price", "$.a.b[2].c". Returns undefined if any segment is
 * missing. No filters/wildcards — intentionally tiny, zero dependencies.
 */
export function jsonPath(root: unknown, path: string | undefined): unknown {
  if (!path) return undefined;
  const cleaned = path.replace(/^\$\.?/, '');
  if (cleaned === '') return root;
  const tokens: string[] = [];
  const re = /[^.[\]]+|\[(\d+)\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(cleaned)) !== null) {
    tokens.push(m[1] ?? m[0]);
  }
  let cur: unknown = root;
  for (const tok of tokens) {
    if (cur == null || typeof cur !== 'object') return undefined;
    cur = (cur as Record<string, unknown>)[tok];
  }
  return cur;
}
