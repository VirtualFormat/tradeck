import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Docker bind mount 下 Turbopack 文件监听不稳定，反复编译。
  // 默认 devcontainer 路径；prod 镜像构建期经 env 覆盖为容器内 /app。
  outputFileTracingRoot:
    process.env.NEXT_PRIVATE_OUTPUT_TRACING_ROOT ?? "/workspace/apps/web",
  // 允许 Next.js Server Component 访问 docker service name
  // 避免 undici 的 DNS 解析问题
  serverExternalPackages: ["undici"],
  // prod 镜像走 standalone 产物（Dockerfile prod 阶段 COPY .next/standalone）；
  // dev（pnpm dev）不受此配置影响。
  output: "standalone",
};

export default nextConfig;
