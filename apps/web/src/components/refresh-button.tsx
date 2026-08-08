/**
 * 手动刷新按钮（客户端组件）
 * - router.refresh() 重新拉取服务端数据（投研看板手动刷新模式，无自动轮询）
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowClockwiseIcon } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function RefreshButton() {
  const router = useRouter();
  const [spinning, setSpinning] = useState(false);

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="刷新数据"
            onClick={() => {
              setSpinning(true);
              router.refresh();
              setTimeout(() => setSpinning(false), 800);
            }}
          />
        }
      >
        <ArrowClockwiseIcon
          className={`size-4 transition-transform ${spinning ? "animate-spin" : ""}`}
        />
      </TooltipTrigger>
      <TooltipContent>刷新数据</TooltipContent>
    </Tooltip>
  );
}
