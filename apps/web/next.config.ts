import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker bind mount 下 Turbopack 文件监听不稳定，反复编译
  // 用 webpack + polling watchOptions 解决
  // 启动时加 --no-turbopack 关闭 Turbopack
  outputFileTracingRoot: "/workspace/apps/web",
};

export default nextConfig;
