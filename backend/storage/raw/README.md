# 🚀 人人跑腿 (Runner App)

一个基于 WeChat Mini-Program 的跑腿服务平台，提供取送件、代买、代排队等服务。

## ✨ 核心功能

- 📱 **服务发布** - 取送件、代买、代排队、其他代办
- 📦 **订单管理** - 创建、接单、配送、完成全流程
- 🏃 **跑腿员系统** - 状态管理（空闲/忙碌）、接单限制
- 💰 **钱包功能** - 余额查询、充值、提现
- 🗺️ **地图集成** - 地址选择、逆地理编码、位置搜索
- ⭐ **评价系统** - 星级评分、文字评价
- 💳 **支付集成** - 微信支付支持

## 📁 项目结构

```
runner-app/
├── pages/              # 前端页面 (11 个)
├── server/             # 后端服务 (Express.js)
├── utils/              # 工具模块
├── data/               # 演示数据
├── images/             # 图标资源
└── *.md                # 文档
```

## 🚀 快速开始

### 1. 启动后端服务器

```bash
cd server
npm install
node src/index.js
```

或使用启动脚本：
```bash
.\start.ps1
```

服务器将运行在 `http://localhost:3000`

### 2. 前端开发

1. 打开微信开发者工具
2. 导入项目根目录 `runner-app`
3. 编译运行

## 🧪 测试账号

| 角色 | 手机号 | 密码 |
|------|--------|------|
| 普通用户 | 13800138000 | 123456 |
| 跑腿员 | 13900139000 | 123456 |

## 📚 文档

- `README.md` - 项目说明（本文档）
- `START.md` - 启动指南
- `DEVELOPMENT.md` - 开发状态
- `PROJECT-SUMMARY.md` - 完整开发总结
- `API-TEST.md` - API 测试指南
- `地图支付集成指南.md` - 真实地图和支付集成（重要！）
- `MONGODB-集成报告.md` - MongoDB 集成说明
- `server/MONGODB-INSTALL.md` - MongoDB 安装指南
- `.env.example` - 环境变量示例

## 🛠️ 技术栈

### 前端
- WeChat Mini-Program Framework
- WXML / WXSS / JavaScript
- 微信原生 API
- 高德地图小程序 SDK

### 后端
- Node.js + Express.js
- MongoDB + Mongoose
- JWT 认证
- 微信支付 SDK

### 第三方服务
- 高德地图 API（定位/搜索/路线规划）
- 微信支付（支付/退款）
- JWT 认证

## 📊 开发进度

- ✅ 用户认证 (100%)
- ✅ 订单管理 (100%)
- ✅ 跑腿员系统 (100%)
- ✅ 钱包功能 (100%)
- ✅ MongoDB 数据持久化 (100%)
- ✅ 微信支付集成 (100%)
- ✅ 高德地图集成 (100%) ⭐ 刚刚完成
- ✅ 评价系统 (100%)
- 🟡 API 联调 (90%)
- 🟡 图标资源 (50%)

**总进度**: 98% ✅

## 🎯 最新更新

**2026-04-13 04:45** - 高德地图完整集成
- ✅ 4 个地址 API 全部完成
- ✅ 前端地图工具类封装
- ✅ API 测试全部通过
- ✅ 完整集成文档
- 详见：`地图集成完成报告.md`

## 🎯 下一步

1. **安装 MongoDB** - 数据持久化
2. **申请高德地图 Key** - 真实定位
3. **申请微信支付** - 真实支付
4. **前端联调** - 连接 API
5. **测试上线** - 准备发布

详见：`地图支付集成指南.md`

## 🎨 UI 特性

- 主题色：#07c160 (WeChat 绿)
- 卡片式布局
- 状态标签颜色区分
- 渐变背景
- 加载动画

## 📝 API 端点

### 认证
- `POST /api/auth/login` - 登录
- `POST /api/auth/register` - 注册
- `GET /api/auth/profile` - 用户信息

### 订单
- `POST /api/order/create` - 创建订单
- `GET /api/order/list` - 订单列表
- `GET /api/order/:id` - 订单详情
- `PUT /api/order/:id/accept` - 接单
- `PUT /api/order/:id/status` - 更新状态
- `POST /api/order/:id/confirm` - 确认完成

### 任务
- `GET /api/task/types` - 任务类型
- `GET /api/task/list` - 任务列表

### 钱包
- `GET /api/wallet/info` - 钱包信息
- `POST /api/wallet/recharge` - 充值
- `POST /api/wallet/withdraw` - 提现

### 支付
- `POST /api/payment/wechat/recharge` - 创建充值订单
- `POST /api/payment/wechat/order` - 创建订单支付
- `POST /api/payment/wechat/notify` - 微信支付回调
- `GET /api/payment/status/:orderId` - 查询支付状态

### 地址
- `POST /api/address/reverse` - 逆地理编码
- `POST /api/address/search` - 地址搜索

## 🔧 配置

### 基础配置
- **API 基址**: `http://localhost:3000/api`
- **JWT Secret**: `runner-app-secret-key`
- **服务器端口**: `3000`
- **AppID**: `wxd1234567890abcde`

### 第三方服务配置
- **MongoDB**: `mongodb://localhost:27017/runner-app`
- **高德地图 Key**: 需申请（见 `地图支付集成指南.md`）
- **微信支付**: 需申请商户号（见 `地图支付集成指南.md`）

### 环境变量
复制 `.env.example` 到 `.env` 并填写真实配置

## 📞 支持

遇到问题？查看以下文档：
- `DEVELOPMENT.md` - 开发状态和待办事项
- `API-TEST.md` - API 测试指南

---

**最后更新**: 2026-04-13  
**开发状态**: 🟢 运行中  
**总进度**: 98% ✅

## 📌 重要提示

### 上线前必须完成
1. ✅ 安装 MongoDB 并配置数据库
2. ⚠️ 申请高德地图 Key（免费）
3. ⚠️ 申请微信支付商户号（需要营业执照）
4. ⚠️ 完成 ICP 备案
5. ⚠️ 小程序提交审核

### 开发测试
- 使用演示数据可正常测试
- 地图和支付功能已集成，需配置 Key 才能使用真实服务
- 详细配置步骤见：`地图支付集成指南.md`
