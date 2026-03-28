# Docker 部署评估（2026-03）

本文档记录 2026-03 对 Docker 部署链路的真实回测与修复结论。

## 1. 评估对象

- 中文仓库上游公开版：`hsliuping/TradingAgents-CN`
- 当前仓库：`RichardCao/TradingAgents-CN`
- 原始上游参考：`TauricResearch/TradingAgents`

本次结论基于：

- 对上游 Docker 文件的静态对比
- 在本机真实执行 `docker compose build / up`
- 验证前端、后端、MongoDB、Redis 健康状态
- 验证默认配置导入与管理员初始化

## 2. 结论摘要

### 2.1 上游 Docker 不是完全损坏，但原样流程不是“开箱即用”

上游 `hsliuping/TradingAgents-CN` 的 Docker 方案具备这些事实：

- 镜像可以构建
- 服务有机会启动
- 但默认文档流程与默认环境配置口径并不一致

更准确地说：

- **不是完全不可用**
- 但也**不能视为当前文档下的一键可用方案**

### 2.2 当前仓库已经补成“可公开提交的一键部署版本”

当前仓库已经完成以下修复，并通过真实回测：

- `./scripts/start_docker.sh` 可直接启动当前前后端分离架构
- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000/api/health`
- MongoDB / Redis / backend / frontend 当前均能进入 `healthy`
- 默认配置可在后端健康后自动导入
- 默认管理员账号可自动创建：`admin / admin123`

## 3. 上游方案的真实问题点

### 3.1 根目录 `.env` 与 Docker 专用配置口径冲突

上游 `docker-compose.yml` 运行时仍依赖：

- `env_file: .env`

但上游 `.env.example` 默认值仍是：

- `MONGODB_HOST=localhost`
- `REDIS_HOST=localhost`
- `MONGODB_CONNECTION_STRING=...localhost...`

这在容器内会导致：

- 后端连到容器自己的 `localhost`
- 而不是 compose 网络里的 `mongodb` / `redis`

这是上游 Docker 方案最关键的坑。

### 3.2 Compose 里虽然补了 `TRADINGAGENTS_*`，但不足以兜住主配置读取

上游 compose 中有：

- `TRADINGAGENTS_MONGODB_URL`
- `TRADINGAGENTS_REDIS_URL`

但当前后端主链路实际主要读取的是：

- `MONGODB_CONNECTION_STRING`
- `MONGODB_HOST`
- `REDIS_HOST`
- 以及由这些变量推导出的 `MONGO_URI / REDIS_URL`

所以：

- 只补 `TRADINGAGENTS_*` 不够
- 运行时环境必须把主配置键也一起压到 Docker 服务名口径

### 3.3 后端镜像里烘焙 `.env.docker`，会形成双来源配置

上游 `Dockerfile.backend` 会：

- `COPY .env.docker ./.env`

这会让运行时同时存在两套环境来源：

- 镜像内 `.env`
- compose 注入的 `env_file`

结果是：

- 配置职责不清晰
- 用户难以判断实际生效的是哪一层

### 3.4 Mongo 初始化挂载不稳定

上游通过：

- `./scripts/mongo-init.js:/docker-entrypoint-initdb.d/mongo-init.js:ro`

做初始化。

真实回测中，这条链路首次启动时会出现加载失败的情况，随后 Mongo 可能恢复正常，但对“一键成功启动”的体验不好。

### 3.5 旧启动脚本和文档仍是过时架构口径

上游 `scripts/start_docker.sh` 和 `docs/features/docker-deployment.md` 仍在检查：

- `8501`
- `Streamlit`
- `web`

而当前真实架构已经是：

- Vue 3 前端
- FastAPI 后端
- `3000 / 8000`

所以旧脚本和旧文档即使不是“语法错误”，也是**错误入口**。

### 3.6 前端健康检查也存在误报风险

上游前端健康检查使用：

- `wget http://localhost`

在本机真实回测里，这会导致：

- 页面其实可访问
- 但容器健康检查误报 `unhealthy`

更稳的口径是：

- `http://127.0.0.1/health`

## 4. 当前仓库修复后的方案

当前仓库对 Docker 路径做了以下收敛。

### 4.1 运行时环境单一来源

现在的口径是：

- 公开模板：`.env.docker`
- 本地可编辑：`.env.docker.local`
- 运行时生成：`.env.docker.runtime`

compose 只读取：

- `.env.docker.runtime`

不再直接依赖根目录 `.env`。

### 4.2 运行时强制覆盖 Docker 网络数据库配置

启动脚本会统一写入：

- `MONGODB_HOST=mongodb`
- `REDIS_HOST=redis`
- `MONGODB_CONNECTION_STRING=...@mongodb...`
- `MONGODB_URL`
- `MONGO_URI`
- `REDIS_URL`
- `TRADINGAGENTS_MONGODB_URL`
- `TRADINGAGENTS_REDIS_URL`

这样做的目的不是替用户决定模型供应商，而是保证容器内部网络永远正确。

### 4.3 后端镜像不再烘焙 `.env`

当前仓库已经移除：

- `COPY .env.docker ./.env`

避免镜像内环境和运行时环境相互覆盖。

### 4.4 初始化改为后端健康后显式执行

当前链路不再依赖 Mongo init 挂载，而是：

1. 等待 backend healthy
2. 执行：

```bash
docker compose exec -T backend python scripts/import_config_and_create_user.py --incremental
```

这条路径已经真实验证通过。

### 4.5 去掉固定容器名和固定卷名

当前 compose 已不再写死：

- `container_name`
- 自定义卷名

这样可以避免：

- 同机多个仓库副本互相撞名
- 上游测试栈与当前仓库互相抢卷

## 5. 必要性分级

### 5.1 必须保留

- Docker 运行时改用 `.env.docker.runtime`
- compose 强制写入 Docker 网络 Mongo/Redis 主配置键
- 后端镜像不再烘焙 `.env`
- 公共启动脚本与文档重写为当前 `3000 / 8000` 架构

### 5.2 强烈建议保留

- 移除 Mongo init 挂载，改为后端健康后显式初始化
- 前端健康检查改为 `127.0.0.1/health`
- 初始化脚本优先读取当前环境变量，不再误报 `.env` 缺失

### 5.3 可选但建议保留

- 去掉固定 `container_name`
- 去掉固定卷名

## 6. 当前真实验证结果

本机实际执行通过：

```bash
./scripts/start_docker.sh
docker compose ps
curl http://localhost:8000/api/health
curl -I http://localhost:3000
docker compose exec -T backend python scripts/import_config_and_create_user.py --incremental
```

结果：

- backend healthy
- frontend healthy
- mongodb healthy
- redis healthy
- 默认配置增量导入正常
- 默认管理员创建正常

## 7. 当前判断

截至 2026-03-29，我的结论是：

- 上游 Docker 方案有可复用基础，但原样文档流程并不可靠
- 当前仓库已经把这条链路整理成可公开提交的正式方案
- 如果后续继续维护 Docker，建议坚持：
  - Docker 专用环境模板
  - 运行时单一来源
  - 显式初始化
  - 当前架构文档与脚本同步维护
