import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker bind mount 下 Turbopack 文件监听不稳定，反复编译
  outputFileTracingRoot: "/workspace/apps/web",
  // 允许 Next.js Server Component 访问 docker service name
  // 避免 undici 的 DNS 解析问题
  serverExternalPackages: ["undici"],
};

export default nextConfig;
