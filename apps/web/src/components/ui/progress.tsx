"use client"

import { Progress as ProgressPrimitive } from "@base-ui/react/progress"

import { cn } from "@/lib/utils"

/**
 * 进度条组件（shadcn progress，base-nova 风格：@base-ui/react 原语）
 * 用法同官方：<Progress value={33} />，value 取 0-100
 */
function Progress({
  className,
  value = 0,
  ...props
}: ProgressPrimitive.Root.Props) {
  // 百分比钳制到 0-100，Indicator 宽度由内联样式控制
  const pct = Math.min(100, Math.max(0, value ?? 0))
  return (
    <ProgressPrimitive.Root
      data-slot="progress"
      value={pct}
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-muted/30",
        className
      )}
      {...props}
    >
      <ProgressPrimitive.Track
        data-slot="progress-track"
        className="h-full w-full"
      >
        <ProgressPrimitive.Indicator
          data-slot="progress-indicator"
          className="h-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </ProgressPrimitive.Track>
    </ProgressPrimitive.Root>
  )
}

export { Progress }
