# Docker 部署指南

## 目标

这套 Docker 方案面向当前仓库的真实架构：

- 前端：Vue 3 + Nginx，默认端口 `3000`
- 后端：FastAPI，默认端口 `8000`
- 数据库：MongoDB，默认端口 `27017`
- 缓存：Redis，默认端口 `6379`

推荐入口是项目自带的一键脚本：

```bash
./scripts/start_docker.sh
```

它会完成以下工作：

- 检查 Docker 与 Docker Compose
- 首次生成本地配置文件 `.env.docker.local`
- 基于本地配置生成运行时文件 `.env.docker.runtime`
- 强制修正 Docker 容器内数据库地址为 `mongodb` / `redis`
- 构建并启动前后端、MongoDB、Redis
- 在后端启动后导入默认配置，并创建默认管理员账号

## 环境要求

- Docker Engine 20+
- Docker Compose v2，或兼容的 `docker-compose`
- 建议 4 GB 以上可用内存
- 建议 10 GB 以上可用磁盘空间

## 快速开始

```bash
git clone <your-repo-url>
cd TradingAgents-CN
./scripts/start_docker.sh
```

首次执行时，如果本地不存在 `.env.docker.local`，脚本会自动从 `.env.docker` 复制一份，并提醒你按需修改。

启动完成后默认访问地址：

- 前端：`http://localhost:3000`
- 后端健康检查：`http://localhost:8000/api/health`

默认管理员账号：

- 用户名：`admin`
- 密码：`admin123`

## 配置文件说明

公开可提交的 Docker 配置模板：

- `.env.docker`

本地可编辑文件：

- `.env.docker.local`

脚本自动生成、仅供运行时使用的文件：

- `.env.docker.runtime`

其中：

- `.env.docker` 可以提交
- `.env.docker.local` 不应提交
- `.env.docker.runtime` 不应提交

## 必填与可选配置

服务本身可以在未填写外部 Key 的情况下启动，但部分能力会不可用。

建议至少填写：

- 一个可用的大模型 Provider Key
  - 例如 `OPENAI_API_KEY`、`DEEPSEEK_API_KEY`、`DASHSCOPE_API_KEY` 等
- 如需更完整的 A 股数据能力，建议填写：
  - `TUSHARE_TOKEN`

常见情况：

- 不填任何 LLM Key：前后端能启动，但分析任务无法真正执行
- 不填 `TUSHARE_TOKEN`：系统仍可运行，但 A 股部分增强数据能力受限

## 为什么不要把 Docker 数据库地址写成 localhost

容器内的后端连接的是 Docker Compose 网络中的服务名，而不是宿主机的 `localhost`。

因此在 Docker 运行时，数据库相关配置必须指向：

- MongoDB：`mongodb`
- Redis：`redis`

启动脚本会在 `.env.docker.runtime` 中强制写入这些值，避免因为本地模板误配导致容器内后端去连接错误的 `localhost`。

## 一键脚本实际做了什么

`./scripts/start_docker.sh` 会自动覆盖以下运行时配置：

- `MONGODB_HOST=mongodb`
- `REDIS_HOST=redis`
- `MONGODB_CONNECTION_STRING=mongodb://admin:tradingagents123@mongodb:27017/tradingagents?authSource=admin`
- `MONGODB_URL` / `MONGO_URI`
- `REDIS_URL=redis://:tradingagents123@redis:6379/0`
- 对应的 `TRADINGAGENTS_MONGODB_URL` / `TRADINGAGENTS_REDIS_URL`

这样做的目的不是替用户决定外部 Provider，而是保证 Docker 内部网络连接一定正确。

## 管理与排障

查看容器状态：

```bash
docker compose ps
```

如果你的环境仍使用旧版命令，也可以使用：

```bash
docker-compose ps
```

查看日志：

```bash
docker compose logs -f backend frontend
docker compose logs -f mongodb redis
```

停止服务：

```bash
docker compose down
```

连同数据卷一起删除：

```bash
docker compose down -v
```

启动可选管理界面：

```bash
docker compose --profile management up -d
```

管理界面端口：

- Redis Commander：`http://localhost:8081`
- Mongo Express：`http://localhost:8082`

## 常见问题

### 1. 脚本提示某些 Key 仍是占位值

这是提醒，不会阻止容器启动。

含义是：

- UI 和基础服务通常仍能启动
- 但对应的分析、同步或模型调用能力还不能正常使用

### 2. 已经有本地 `.env`

Docker 部署默认不再读取宿主机根目录 `.env` 作为主入口，避免把本地开发配置误带进容器。

Docker 运行时请优先使用：

- `.env.docker.local`
- `.env.docker.runtime`

### 3. 初始化默认账号失败怎么办

脚本会在后端健康检查通过后自动执行：

```bash
docker compose exec -T backend python scripts/import_config_and_create_user.py --incremental
```

如果失败，可先查看后端日志，再手动重试这条命令。
