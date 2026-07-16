"use client"

import * as React from "react"

import { NavDocuments } from "@/components/nav-documents"
import { NavMain } from "@/components/nav-main"
import { NavSecondary } from "@/components/nav-secondary"
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
  FlameIcon,
  NewspaperIcon,
  ChartBarIcon,
  GearIcon,
  QuestionIcon,
  ChartLineIcon,
  FileTextIcon,
} from "@phosphor-icons/react"

const data = {
  user: {
    name: "tradeck",
    email: "v0.1",
    avatar: "/avatars/shadcn.jpg",
  },
  navMain: [
    { title: "看板", url: "/", icon: <SquaresFourIcon /> },
    { title: "自选 / 筛选", url: "/screener", icon: <StarIcon /> },
    { title: "热力图", url: "/heatmap", icon: <FlameIcon /> },
    { title: "新闻流", url: "/news", icon: <NewspaperIcon /> },
    { title: "宏观数据", url: "/macro", icon: <ChartBarIcon /> },
  ],
  navSecondary: [
    { title: "设置", url: "#", icon: <GearIcon /> },
    { title: "帮助", url: "#", icon: <QuestionIcon /> },
  ],
  documents: [
    { name: "行情数据", url: "#", icon: <ChartLineIcon /> },
    { name: "研究报告", url: "#", icon: <FileTextIcon /> },
  ],
}

export function AppSidebar({ ...props }: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              className="data-[slot=sidebar-menu-button]:p-1.5!"
              render={<a href="/" />}
            >
              <ChartLineIcon className="size-5!" />
              <span className="text-base font-semibold">tradeck</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain items={data.navMain} />
        <NavDocuments items={data.documents} />
        <NavSecondary items={data.navSecondary} className="mt-auto" />
      </SidebarContent>
      <SidebarFooter>
        <NavUser user={data.user} />
      </SidebarFooter>
    </Sidebar>
  )
}
