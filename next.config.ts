import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 独立运行包：本地构建后上传 .next/standalone，服务器只需装 Node 即可运行，
  // 保留动态路由 (/game/[id] /difficulty/[id])，无需预生成参数。
  output: "standalone",
  // 关闭 Next.js 图片优化，避免服务器上再装 sharp
  images: { unoptimized: true },
};

export default nextConfig;
