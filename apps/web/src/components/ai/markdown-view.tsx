"use client";

import ReactMarkdown, { type Options } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import { cn } from "@/lib/utils";
import { normalizeMathDelimiters } from "@/lib/markdown";

const remarkPlugins: Options["remarkPlugins"] = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
];

const components: Options["components"] = {
  // 金融表格偏宽：包 typeset-scroll 横向滚动
  table: (all) => {
    const { node, ...props } = all as { node?: unknown } & Record<string, unknown>;
    void node;
    return (
      <div className="typeset-scroll">
        <table {...props} />
      </div>
    );
  },
  a: (all) => {
    const { node, ...props } = all as { node?: unknown } & Record<string, unknown>;
    void node;
    return <a {...props} target="_blank" rel="noopener noreferrer" />;
  },
};

interface MarkdownViewProps {
  content: string;
  /** chat=问答气泡(紧凑) / report=研究报告(宽松) */
  variant?: "chat" | "report";
  /** 流式中不挂 rehype（md 半途不完整，KaTeX/highlight 会崩），结束后完整渲染 */
  streaming?: boolean;
  className?: string;
}

export function MarkdownView({
  content,
  variant = "chat",
  streaming = false,
  className,
}: MarkdownViewProps) {
  return (
    <div
      className={cn(
        "typeset",
        variant === "chat" ? "typeset-chat" : "typeset-report",
        className
      )}
    >
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={streaming ? [] : [rehypeHighlight, rehypeKatex]}
        components={components}
      >
        {normalizeMathDelimiters(content)}
      </ReactMarkdown>
    </div>
  );
}
