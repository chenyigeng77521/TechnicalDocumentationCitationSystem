import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 抑制水合错误警告（由浏览器扩展引起）
  reactStrictMode: true,
};

export default nextConfig;
