/**
 * 登录页（Server Component）
 * 已有 session 访问 /login 直接回跳首页。
 */
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { getSession } from "@/lib/auth";

import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "登录 — tradeck",
};

/** 防开放重定向：只允许以 / 开头的站内相对路径 */
function safeNext(next: string | undefined): string {
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/";
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;

  // 已登录用户带 next 访问 /login 时尊重回跳意图（与 LoginForm 成功后的
  // router.push(next) 对称），而非一律吞掉 next 回首页。
  const user = await getSession();
  if (user) redirect(safeNext(next));

  return (
    <main className="flex min-h-svh items-center justify-center bg-background p-4">
      <LoginForm next={safeNext(next)} />
    </main>
  );
}
