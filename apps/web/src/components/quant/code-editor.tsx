"use client";

/**
 * 策略代码编辑器：CodeMirror 6 + Python 语法高亮（quant AI 工作台专用）。
 *
 * 选 CodeMirror 而非 Monaco：无 CDN/web worker 依赖、体积小、纯本地渲染；
 * @uiw/react-codemirror 是 React 薄封装。主题色全部走 globals.css 的 preset
 * 令牌（--background/--foreground 等），深浅色随 <html class="dark"> 自动生效。
 */
import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

// 语法高亮配色：全站强制深色（<html class="dark">），defaultHighlightStyle
// 是浅色配色（深灰字配浅底），在深色底下完全看不见——必须显式给一套深色
// token 配色。色值全部走 globals.css 的 preset 令牌（chart 色系 + 语义色），
// 与站内图表同一调色板，不写死 hex。
const highlight = HighlightStyle.define([
  // 关键字 / 控制流：主强调色（violet 系 chart-1）
  { tag: [tags.keyword, tags.controlKeyword, tags.moduleKeyword], color: "var(--chart-1)" },
  // 字符串 / 文档串：绿色（--down 同款语义，但取 chart 色系避免涨跌歧义）
  { tag: [tags.string, tags.docString, tags.special(tags.string)], color: "var(--chart-2)" },
  // 数字 / 布尔 / None：亮橙（chart-3 偏紫，这里用 chart-4 拉开层次）
  { tag: [tags.number, tags.bool, tags.null, tags.atom], color: "var(--chart-4)" },
  // 函数名 / 方法名：亮青（chart-5）
  { tag: [tags.function(tags.variableName), tags.function(tags.propertyName)], color: "var(--chart-5)" },
  // 类名 / 类型注解：primary 前景（亮白）
  { tag: [tags.className, tags.typeName, tags.namespace], color: "var(--primary)" },
  // 注释：弱化
  { tag: [tags.comment, tags.blockComment], color: "var(--muted-foreground)", fontStyle: "italic" },
  // 运算符 / 标点：正文色降一档
  { tag: [tags.operator, tags.punctuation, tags.separator], color: "var(--foreground)" },
  // 变量 / 属性：正文色
  { tag: [tags.variableName, tags.propertyName], color: "var(--foreground)" },
  // 定义（def foo / class Bar 的名字）：主强调
  { tag: [tags.definition(tags.variableName), tags.definition(tags.function(tags.variableName))], color: "var(--chart-1)" },
  // 装饰器 / self / 特殊变量
  { tag: [tags.meta, tags.annotation, tags.self], color: "var(--chart-3)" },
  // 无效/错误：destructive
  { tag: tags.invalid, color: "var(--destructive)" },
]);

// 编辑器容器/行号/选区色：同样全走 preset 令牌
const theme = EditorView.theme({
  "&": {
    backgroundColor: "transparent",
    color: "var(--foreground)",
    fontSize: "12px",
  },
  ".cm-content": {
    fontFamily: "var(--font-mono)",
    caretColor: "var(--foreground)",
    padding: "12px 0",
  },
  ".cm-line": { padding: "0 16px" },
  "&.cm-focused": { outline: "none" },
  ".cm-gutters": {
    backgroundColor: "transparent",
    color: "var(--muted-foreground)",
    border: "none",
    fontFamily: "var(--font-mono)",
  },
  ".cm-activeLine": { backgroundColor: "color-mix(in srgb, var(--muted) 40%, transparent)" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--foreground)" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor: "color-mix(in srgb, var(--accent) 70%, transparent) !important",
  },
  ".cm-cursor": { borderLeftColor: "var(--foreground)" },
});

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  height?: string;
}

export function CodeEditor({
  value,
  onChange,
  readOnly = false,
  height = "520px",
}: CodeEditorProps) {
  return (
    <div className="overflow-hidden rounded-lg border bg-muted/30 text-xs leading-relaxed [&_.cm-editor]:h-full">
      <CodeMirror
        value={value}
        onChange={onChange}
        extensions={[python(), theme, syntaxHighlighting(highlight)]}
        readOnly={readOnly}
        editable={!readOnly}
        height={height}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          autocompletion: false,
          searchKeymap: true,
          // 关掉 basicSetup 自带的 defaultHighlightStyle fallback，
          // 否则浅色 token 配色会盖掉我们的深色 HighlightStyle
          syntaxHighlighting: false,
        }}
        aria-label="策略代码编辑器"
      />
    </div>
  );
}
