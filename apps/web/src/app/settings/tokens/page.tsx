/**
 * API 令牌设置页
 * 路由：/settings/tokens
 * 管理个人访问令牌（PAT，供 MCP 客户端连接 tradeck 上传策略、跑回测）；
 * 列表 / 签发 / 撤销全部经 Next 代理路由 /api/account/tokens，不直连 api 服务
 */
import { KeyIcon } from "@phosphor-icons/react/dist/ssr";

import { ApiTokensPanel } from "@/components/settings/api-tokens-panel";
import { requireUser } from "@/lib/auth";

export const metadata = { title: "API 令牌 · tradeck" };

export default async function ApiTokensPage() {
  // 远端校验 session：无效直接跳登录页（middleware 只查 cookie 存在与否）
  await requireUser();

  return (
    <main className="mx-auto w-full max-w-7xl space-y-4 p-4 md:p-6">
      <div className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <KeyIcon className="size-5" />
          API 令牌
        </h1>
        <p className="text-sm text-muted-foreground">
          个人访问令牌供 MCP 客户端（IDE / CLI agent）以你的身份连接 tradeck，
          读取指南、保存策略与提交回测
        </p>
      </div>
      <ApiTokensPanel />
    </main>
  );
}
