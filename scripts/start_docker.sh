#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_ENV="$PROJECT_ROOT/.env.docker"
LOCAL_ENV="$PROJECT_ROOT/.env.docker.local"
RUNTIME_ENV="$PROJECT_ROOT/.env.docker.runtime"

BACKEND_URL="http://localhost:8000/api/health"
FRONTEND_URL="http://localhost:3000"
MONGODB_URI="mongodb://admin:tradingagents123@mongodb:27017/tradingagents?authSource=admin"
REDIS_URI="redis://:tradingagents123@redis:6379/0"

info() {
    printf '[INFO] %s\n' "$1"
}

warn() {
    printf '[WARN] %s\n' "$1"
}

error() {
    printf '[ERROR] %s\n' "$1" >&2
}

detect_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD=(docker compose)
        return
    fi

    if command -v docker-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(docker-compose)
        return
    fi

    error "未找到 Docker Compose。请安装 docker compose 或 docker-compose。"
    exit 1
}

escape_sed_replacement() {
    printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

upsert_env() {
    local file="$1"
    local key="$2"
    local value="$3"
    local escaped_value
    escaped_value="$(escape_sed_replacement "$value")"

    if grep -Eq "^${key}=" "$file"; then
        sed -i.bak -E "s|^${key}=.*|${key}=${escaped_value}|" "$file"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$file"
    fi
}

cleanup_sed_backups() {
    find "$PROJECT_ROOT" -maxdepth 1 -name '*.bak' -delete >/dev/null 2>&1 || true
}

ensure_local_env() {
    if [[ -f "$LOCAL_ENV" ]]; then
        return
    fi

    if [[ ! -f "$TEMPLATE_ENV" ]]; then
        error "缺少模板文件 .env.docker，无法生成本地 Docker 配置。"
        exit 1
    fi

    cp "$TEMPLATE_ENV" "$LOCAL_ENV"
    warn "已生成 ${LOCAL_ENV}。"
    warn "请按需填写 LLM Provider、API Key、Tushare Token 等信息。"
}

prepare_runtime_env() {
    cp "$LOCAL_ENV" "$RUNTIME_ENV"

    upsert_env "$RUNTIME_ENV" "DOCKER_CONTAINER" "true"
    upsert_env "$RUNTIME_ENV" "MONGODB_ENABLED" "true"
    upsert_env "$RUNTIME_ENV" "REDIS_ENABLED" "true"
    upsert_env "$RUNTIME_ENV" "MONGODB_HOST" "mongodb"
    upsert_env "$RUNTIME_ENV" "MONGODB_PORT" "27017"
    upsert_env "$RUNTIME_ENV" "MONGODB_USERNAME" "admin"
    upsert_env "$RUNTIME_ENV" "MONGODB_PASSWORD" "tradingagents123"
    upsert_env "$RUNTIME_ENV" "MONGODB_DATABASE" "tradingagents"
    upsert_env "$RUNTIME_ENV" "MONGODB_DATABASE_NAME" "tradingagents"
    upsert_env "$RUNTIME_ENV" "MONGODB_AUTH_SOURCE" "admin"
    upsert_env "$RUNTIME_ENV" "MONGODB_CONNECTION_STRING" "$MONGODB_URI"
    upsert_env "$RUNTIME_ENV" "MONGODB_URL" "$MONGODB_URI"
    upsert_env "$RUNTIME_ENV" "MONGO_URI" "$MONGODB_URI"
    upsert_env "$RUNTIME_ENV" "MONGO_DB" "tradingagents"
    upsert_env "$RUNTIME_ENV" "USE_MONGODB_STORAGE" "true"
    upsert_env "$RUNTIME_ENV" "REDIS_HOST" "redis"
    upsert_env "$RUNTIME_ENV" "REDIS_PORT" "6379"
    upsert_env "$RUNTIME_ENV" "REDIS_PASSWORD" "tradingagents123"
    upsert_env "$RUNTIME_ENV" "REDIS_DB" "0"
    upsert_env "$RUNTIME_ENV" "REDIS_URL" "$REDIS_URI"
    upsert_env "$RUNTIME_ENV" "TRADINGAGENTS_MONGODB_URL" "$MONGODB_URI"
    upsert_env "$RUNTIME_ENV" "TRADINGAGENTS_REDIS_URL" "$REDIS_URI"
    upsert_env "$RUNTIME_ENV" "TRADINGAGENTS_CACHE_TYPE" "redis"

    cleanup_sed_backups
}

read_env_value() {
    local file="$1"
    local key="$2"
    local line

    line="$(grep -E "^${key}=" "$file" | tail -n 1 || true)"
    printf '%s' "${line#*=}"
}

is_placeholder_value() {
    local value="$1"
    local normalized

    normalized="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"

    [[ -z "$normalized" ]] && return 0
    [[ "$normalized" == *"placeholder"* ]] && return 0
    [[ "$normalized" == your_* ]] && return 0
    [[ "$normalized" == your-* ]] && return 0
    [[ "$normalized" == *"_here" ]] && return 0
    [[ "$normalized" == "changeme" ]] && return 0
    [[ "$normalized" == "null" ]] && return 0

    return 1
}

report_placeholder_keys() {
    local keys=(
        OPENAI_API_KEY
        DEEPSEEK_API_KEY
        DASHSCOPE_API_KEY
        GOOGLE_API_KEY
        AI302_API_KEY
        OPENROUTER_API_KEY
        ANTHROPIC_API_KEY
        TUSHARE_TOKEN
        CUSTOM_OPENAI_API_KEY
    )
    local missing=()
    local key
    local value

    for key in "${keys[@]}"; do
        value="$(read_env_value "$RUNTIME_ENV" "$key")"
        if is_placeholder_value "$value"; then
            missing+=("$key")
        fi
    done

    if [[ "${#missing[@]}" -eq 0 ]]; then
        return
    fi

    warn "以下配置仍是占位值，服务可启动，但相关功能会不可用或受限："
    for key in "${missing[@]}"; do
        warn "  - $key"
    done
}

wait_for_url() {
    local name="$1"
    local url="$2"
    local attempts="$3"
    local sleep_seconds="$4"
    local i

    for ((i=1; i<=attempts; i++)); do
        if curl -fsS "$url" >/dev/null 2>&1; then
            info "$name 已就绪。"
            return 0
        fi

        sleep "$sleep_seconds"
    done

    error "$name 启动超时，请检查容器日志。"
    return 1
}

run_initialization() {
    info "导入默认配置并创建默认管理员账号..."
    "${COMPOSE_CMD[@]}" exec -T backend \
        python scripts/import_config_and_create_user.py --incremental
}

main() {
    cd "$PROJECT_ROOT"

    info "检查 Docker daemon..."
    if ! docker info >/dev/null 2>&1; then
        error "Docker 未运行，请先启动 Docker。"
        exit 1
    fi

    detect_compose_cmd

    mkdir -p logs data config
    ensure_local_env
    prepare_runtime_env
    report_placeholder_keys

    info "使用 ${COMPOSE_CMD[*]} 启动容器..."
    "${COMPOSE_CMD[@]}" up -d --build

    info "等待后端健康检查通过..."
    wait_for_url "后端" "$BACKEND_URL" 120 2

    info "等待前端可访问..."
    wait_for_url "前端" "$FRONTEND_URL" 120 2

    run_initialization

    info "Docker 部署完成。"
    printf '\n'
    printf '前端地址: %s\n' "$FRONTEND_URL"
    printf '后端地址: http://localhost:8000\n'
    printf '默认登录: admin / admin123\n'
    printf '\n'
    printf '提示:\n'
    printf '  1. 至少配置一个可用的大模型 Key，分析功能才能正常工作。\n'
    printf '  2. A 股增强能力建议额外填写 TUSHARE_TOKEN。\n'
    printf '  3. 本地可编辑文件: .env.docker.local\n'
    printf '  4. 运行时文件: .env.docker.runtime（已加入忽略，不要提交）\n'
    printf '\n'
    printf '常用命令:\n'
    printf '  启动管理面板: %s --profile management up -d\n' "${COMPOSE_CMD[*]}"
    printf '  查看容器状态: %s ps\n' "${COMPOSE_CMD[*]}"
    printf '  查看日志: %s logs -f backend frontend\n' "${COMPOSE_CMD[*]}"
    printf '  停止服务: %s down\n' "${COMPOSE_CMD[*]}"
}

main "$@"
