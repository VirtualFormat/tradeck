"use client"

import { usePathname } from "next/navigation"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { cn } from "@/lib/utils"

const TITLES: Record<string, string> = {
  "/": "看板",
  "/screener": "自选 / 筛选",
  "/heatmap": "热力图",
  "/news": "新闻流",
  "/macro": "宏观数据",
}

function titleFromPath(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname]
  if (pathname.startsWith("/stocks/")) return "个股详情"
  return "tradeck"
}

export function SiteHeader() {
  const pathname = usePathname()
  const isHome = pathname === "/"
  const isMarketPage = pathname.startsWith("/markets/")

  return (
    <header
      className={cn(
        "h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-(--header-height)",
        isMarketPage ? "hidden" : isHome ? "flex md:hidden" : "flex"
      )}
    >
      <div className="flex w-full items-center gap-1 px-4 lg:gap-2 lg:px-6">
        <SidebarTrigger className="-ml-1" />
        <Separator
          orientation="vertical"
          className="mx-2 h-4 data-vertical:self-auto"
        />
        <h1 className="text-base font-medium">{titleFromPath(pathname)}</h1>
      </div>
    </header>
  )
}
