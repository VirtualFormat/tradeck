"use client"

import * as React from "react"
import Link from "next/link"

import { NavMain, type NavItem } from "@/components/nav-main"
import { NavUser } from "@/components/nav-user"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar"
import {
  SquaresFourIcon,
  StarIcon,
  NewspaperIcon,
  ChartBarIcon,
  ChartLineIcon,
  FlagIcon,
  BankIcon,
  CityIcon,
  GlobeIcon,
} from "@phosphor-icons/react"

const navMain: NavItem[] = [
  {
    title: "总看板",
    url: "/",
    icon: <SquaresFourIcon />,
    items: [
      { title: "A股", url: "/markets/cn", icon: <FlagIcon /> },
      { title: "美股", url: "/markets/us", icon: <BankIcon /> },
      { title: "港股", url: "/markets/hk", icon: <CityIcon /> },
    ],
  },
  { title: "自选 / 筛选", url: "/screener", icon: <StarIcon /> },
  { title: "新闻流", url: "/news", icon: <NewspaperIcon /> },
  { title: "全球宏观", url: "/global", icon: <GlobeIcon /> },
  { title: "宏观数据", url: "/macro", icon: <ChartBarIcon /> },
]

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              className="data-[slot=sidebar-menu-button]:p-1.5!"
              render={<Link href="/" />}
            >
              <ChartLineIcon className="size-5!" />
              <span className="text-base font-semibold">tradeck</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={navMain} />
      </SidebarContent>
      <SidebarFooter>
        <NavUser
          user={{ name: "tradeck", email: "v0.1", avatar: "/avatars/shadcn.jpg" }}
        />
      </SidebarFooter>
    </Sidebar>
  )
}
