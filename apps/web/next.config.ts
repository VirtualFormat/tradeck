import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 允许容器内 dev server 被 host 访问
  // Docker bind mount 下 Next.js 需要 polling
  experimental: {
    // Next.js 15+ 用 turbo，但 docker 下 polling 更稳
  },
};

export default nextConfig;
