"use client";

import { GearIcon, MoonIcon } from "@phosphor-icons/react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";

export function ThemeToggle() {
  const { isMobile } = useSidebar();

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <SidebarMenuButton
                tooltip="设置"
                aria-label="设置主题"
                className="aria-expanded:bg-sidebar-accent aria-expanded:text-sidebar-accent-foreground"
              />
            }
          >
            <GearIcon />
            <span>设置</span>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="min-w-44"
            side={isMobile ? "top" : "right"}
            align="end"
            sideOffset={4}
          >
            <DropdownMenuItem disabled>
              <MoonIcon />
              深色主题
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
