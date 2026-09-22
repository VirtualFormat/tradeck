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
import { EditorView } from "@codemirror/view";

// 主题只映射 preset CSS 变量，不写死色值（mist 深色下与全站一致）
const theme = EditorView.theme({
  "&": {
    backgroundColor: "transparent",
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
        extensions={[python(), theme]}
        readOnly={readOnly}
        editable={!readOnly}
        height={height}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          autocompletion: false,
          searchKeymap: true,
        }}
        aria-label="策略代码编辑器"
      />
    </div>
  );
}
