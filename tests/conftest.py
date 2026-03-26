import os
import sys

import pytest

# 将项目根目录加入 sys.path，确保 `import tradingagents` 可用
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def require_env(name: str) -> str:
    """
    获取外部测试所需环境变量；若未配置则跳过测试。
    """
    value = os.getenv(name, "").strip()
    if not value:
        pytest.skip(f"{name} 未配置，跳过外部集成测试")
    return value
