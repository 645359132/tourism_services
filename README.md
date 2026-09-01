# 智慧景区旅游服务系统

这是一个正在按纵向检查点实现的全栈 MVP。仓库保留既有 HarmonyOS ArkTS/ArkUI Stage 客户端，并将在 `server/` 中提供 FastAPI 服务端。

当前基线：

- `client/`：DevEco Studio 生成的 phone/tablet Hello World 工程，SDK 配置保持不变。
- `server/`：服务端将在功能分支中实现。
- 默认运行模式：SQLite 与进程内降级，无需外部服务。
- 完整运行模式：PostgreSQL 与 Redis，配置由 Docker Compose 提供。

具体交付顺序见 [PLAN.md](PLAN.md)，实际状态见 [PROGRESS.md](PROGRESS.md)。最终启动、测试、演示账号、架构、创新点与外部能力边界会在验收检查点补全。

