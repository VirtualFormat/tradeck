"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
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

function isUrlActive(pathname: string, url: string) {
  return url === "/" ? pathname === "/" : pathname.startsWith(url)
}

export function NavMain({
  items,
  label,
}: {
  items: NavItem[]
  label?: string
}) {
  const pathname = usePathname()
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
                isUrlActive(pathname, sub.url)
              )
              const selfActive = isUrlActive(pathname, item.url)
              return (
                <Collapsible
                  key={item.title}
                  defaultOpen={childActive || selfActive}
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
                            isActive={isUrlActive(pathname, sub.url)}
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
                  isActive={isUrlActive(pathname, item.url)}
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
