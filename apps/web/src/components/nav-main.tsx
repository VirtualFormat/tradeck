"use client"

import Link from "next/link"
import { usePathname, useSearchParams } from "next/navigation"
import { Suspense } from "react"
import { CaretRightIcon } from "@phosphor-icons/react"

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type NavItem = {
  title: string
  url: string
  icon?: React.ReactNode
  items?: { title: string; url: string; icon?: React.ReactNode }[]
}

// url 含 query（如 /quant?tab=mining）时，需同时匹配 pathname 与 query 才算激活；
// 纯路径 url 仍按前缀匹配（沿用旧行为）。
function isUrlActive(pathname: string, url: string, search: string) {
  const qi = url.indexOf("?")
  if (qi >= 0) {
    return pathname === url.slice(0, qi) && search === url.slice(qi)
  }
  return url === "/" ? pathname === "/" : pathname.startsWith(url)
}

function NavMainView({
  items,
  label,
  pathname,
  search,
}: {
  items: NavItem[]
  label?: string
  pathname: string
  search: string
}) {
  const { isMobile, setOpenMobile } = useSidebar()
  const closeMobileSidebar = () => {
    if (isMobile) setOpenMobile(false)
  }
  return (
    <SidebarGroup>
      {label && <SidebarGroupLabel>{label}</SidebarGroupLabel>}
      <SidebarGroupContent className="flex flex-col gap-2">
        <SidebarMenu>
          {items.map((item) => {
            if (item.items && item.items.length > 0) {
              const childActive = item.items.some((sub) =>
                isUrlActive(pathname, sub.url, search)
              )
              // 一级：仅当无二级命中时按自身 url 高亮（有二级时让位给具体二级）
              const selfActive =
                !childActive && isUrlActive(pathname, item.url, search)
              return (
                <Collapsible
                  key={item.title}
                  // 固定默认展开：defaultOpen 若依赖激活态会导致 SSR（无 query）
                  // 与 CSR（有 query）的 data-open 属性不一致，触发 hydration 不匹配。
                  // 一级菜单项少，始终展开体验一致且消除 SSR/CSR 分叉。
                  defaultOpen
                  className="group/collapsible"
                  render={<SidebarMenuItem />}
                >
                  <SidebarMenuButton
                    tooltip={item.title}
                    isActive={selfActive}
                    render={<Link href={item.url} />}
                    onClick={closeMobileSidebar}
                  >
                    {item.icon}
                    <span>{item.title}</span>
                  </SidebarMenuButton>
                  <CollapsibleTrigger
                    aria-label={`展开${item.title}子菜单`}
                    className="absolute top-1 right-1 flex size-6 items-center justify-center rounded-md text-sidebar-foreground outline-hidden hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring"
                  >
                    <CaretRightIcon className="transition-transform duration-200 group-data-open/collapsible:rotate-90" />
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <SidebarMenuSub>
                      {item.items.map((sub) => (
                        <SidebarMenuSubItem key={sub.title}>
                          <SidebarMenuSubButton
                            isActive={isUrlActive(pathname, sub.url, search)}
                            render={<Link href={sub.url} />}
                            onClick={closeMobileSidebar}
                          >
                            {sub.icon}
                            <span>{sub.title}</span>
                          </SidebarMenuSubButton>
                        </SidebarMenuSubItem>
                      ))}
                    </SidebarMenuSub>
                  </CollapsibleContent>
                </Collapsible>
              )
            }
            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  tooltip={item.title}
                  isActive={isUrlActive(pathname, item.url, search)}
                  render={<Link href={item.url} />}
                  onClick={closeMobileSidebar}
                >
                  {item.icon}
                  <span>{item.title}</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

function NavMainInner(props: { items: NavItem[]; label?: string }) {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const search = searchParams.toString() ? `?${searchParams.toString()}` : ""
  return <NavMainView {...props} pathname={pathname} search={search} />
}

// SSR 兜底：search 为空（二级含 query 不高亮），与服务端 HTML 一致防 hydration 不匹配
function NavMainFallback(props: { items: NavItem[]; label?: string }) {
  const pathname = usePathname()
  return <NavMainView {...props} pathname={pathname} search="" />
}

export function NavMain(props: { items: NavItem[]; label?: string }) {
  return (
    <Suspense fallback={<NavMainFallback {...props} />}>
      <NavMainInner {...props} />
    </Suspense>
  )
}
