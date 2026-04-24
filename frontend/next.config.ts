import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 抑制水合错误警告（由浏览器扩展引起）
  reactStrictMode: true,
  // 允许局域网访问（开发模式）
  //在旧版本的 Next.js 或者某些特定配置下，allowedDevOrigins 的默认行为可能比较宽松。
  // allowedDevOrigins 这个地址限制只对 curl postman 等api 攻击有效
  allowedDevOrigins: ['192.168.3.196', 'localhost','172.25.178.137','172.25.178.139'],

  // API 代理配置：将 /api/* 请求转发到后端服务
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:3002/api/:path*',
      },
    ];
  },
};

export default nextConfig;
