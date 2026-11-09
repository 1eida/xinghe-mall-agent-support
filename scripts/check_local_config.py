"""Validate the local Qwen configuration without displaying any credential."""

from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values


def main() -> int:
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.is_file():
        print("未找到项目 .env 文件，请先创建并配置 Qwen。")
        return 1

    values = dotenv_values(path)
    mode = (values.get("CUSTOMER_SUPPORT_MODE") or "").strip().lower()
    if mode not in {"qwen", "auto"}:
        print("请在 .env 中将 CUSTOMER_SUPPORT_MODE 设为 qwen 或 auto。")
        return 1

    required = ("DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_MODEL")
    missing = []
    for key in required:
        value = (values.get(key) or "").strip()
        lowered = value.lower()
        if not value or any(
            placeholder in lowered
            for placeholder in ("replace-with", "your-workspace", "your_api_key", "your-api-key", "<your", "填写")
        ):
            missing.append(key)
    if missing:
        print("请在本项目 .env 中填写：" + ", ".join(missing))
        print("API Key 只需填在本机文件中，不要发送给他人。")
        return 1

    parsed = urlparse((values.get("DASHSCOPE_BASE_URL") or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        print("请检查 .env 中的 DASHSCOPE_BASE_URL 是否为完整的 HTTP(S) 地址。")
        return 1
    print("Qwen 配置项已填写；实际可用性需要进行联网调用验证。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
