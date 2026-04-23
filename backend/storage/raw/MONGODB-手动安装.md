# MongoDB 手动安装指南

## 当前状态

❌ MongoDB 未安装

## 手动安装步骤

### 步骤 1: 下载 MongoDB

打开浏览器，访问：
```
https://www.mongodb.com/try/download/community
```

或者直接使用这个链接下载 Windows 版本：
```
https://fastdl.mongodb.org/windows/mongodb-windows-x86_64-7.0.6-signed.msi
```

**文件大小**: 约 90MB  
**预计下载时间**: 3-8 分钟（取决于网速）

---

### 步骤 2: 安装 MongoDB

1. 双击下载的 `.msi` 文件
2. 点击 "Next"
3. 接受许可协议 → "Next"
4. **重要**: 选择 "Complete"（完整安装）→ "Next"
5. 点击 "Install"
6. 等待安装完成（约 2-5 分钟）
7. 点击 "Finish"

---

### 步骤 3: 验证安装

安装完成后，打开 PowerShell（不需要管理员权限），运行：

```powershell
cd C:\Users\lengh\AppData\Roaming\winclaw\.openclaw\workspace\runner-app\server
node test-mongodb.js
```

如果看到以下输出，说明安装成功：
```
✅ MongoDB 连接成功
✅ 测试集合创建成功
✅ 测试集合删除成功
所有测试通过！
```

---

### 步骤 4: 启动后端服务器

验证成功后，运行：

```powershell
cd C:\Users\lengh\AppData\Roaming\winclaw\.openclaw\workspace\runner-app\server
node src/index.js
```

如果看到以下输出，说明服务器启动成功：
```
🚀 服务器运行在 http://localhost:3000
✅ MongoDB 连接成功
```

---

## 常见问题

### Q1: 下载速度慢？
- 使用国内镜像：https://mirrors.tuna.tsinghua.edu.cn/mongodb-win32-x86_64-7.0.6-signed.msi

### Q2: 安装失败？
- 确保有足够的磁盘空间（至少 500MB）
- 关闭杀毒软件 temporarily
- 重启电脑后重试

### Q3: 服务无法启动？
- 检查端口 27017 是否被占用
- 以管理员身份运行 PowerShell，执行：
  ```powershell
  netstat -ano | findstr :27017
  ```

---

## 下一步

安装完成后，告诉我"MongoDB 安装完成"，我会：

1. ✅ 启动后端服务器
2. ✅ 运行完整的 API 测试
3. ✅ 测试小程序功能

---

**现在请手动下载并安装 MongoDB，完成后告诉我！** 💪
