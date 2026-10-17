/**
 * Markdown 数学公式定界符归一化（借鉴 Vibe-Trading 前端）。
 * LLM 常用 \(...\) / \[...\] 作为 LaTeX 定界符，但 remark-math 只识别 $ 形式；
 * 单 $ 必须关闭（金融文本 "from $150 to $120" 会被误判为公式），
 * 故统一归一到 remark-math 接受的 $$ 形式。围栏/行内代码原样保留。
 */

const CODE_SEGMENT = /(```[\s\S]*?(?:```|$)|~~~[\s\S]*?(?:~~~|$)|`[^`\n]*`)/g;

function normalizeSegment(segment: string): string {
  return segment
    .replace(/\\\[([\s\S]+?)\\\]/g, (_m, expr: string) => `\n\n$$\n${expr.trim()}\n$$\n\n`)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_m, expr: string) => `$$${expr.trim()}$$`);
}

export function normalizeMathDelimiters(content: string): string {
  return content
    .split(CODE_SEGMENT)
    .map((segment, index) => (index % 2 === 1 ? segment : normalizeSegment(segment)))
    .join("");
}
