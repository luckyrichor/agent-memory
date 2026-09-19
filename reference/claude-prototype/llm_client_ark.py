"""
llm_client_ark.py
------------------
真实LLM调用的实现，对接火山方舟(Volcengine Ark)的OpenAI兼容接口。

设计要点（对应我们聊过的知识点的延伸）：
1. 依然实现 memory_extractor.LLMClient 这个抽象接口——
   这就是"依赖倒置"设计真正开始体现价值的地方：extractor.py / retriever.py
   一行代码都不用改，只需要把 MockLLMClient 换成这里的 ArkLLMClient。

2. 【新增知识点】多模型 fallback（容灾/降级）：
   企业级系统很少只依赖单一模型/单一供应商，原因很直接——
   任何一个模型都可能因为限流、临时故障、内容审核误判等原因单次调用失败，
   如果没有降级策略，一次偶发故障就会让整条记忆写入链路当场失败。
   这里实现的策略（用户指定的）：
   - 对同一个模型，失败先重试最多3次（应对偶发的网络抖动/限流）
   - 3次都失败，换下一个模型再试（应对这个模型本身在闹脾气/被下线维护）
   - 模型列表按"更省token优先"排序，因为省钱的模型能满足大部分简单判断任务，
     没必要每次都用最贵最强的模型去做"这句话该不该存"这种轻量判断
     （这其实是我们很早讨论过的"过度设计"问题的另一种体现：
      用最强模型做所有任务，属于没必要的成本，能力和成本要按任务匹配）
"""

import os
import time

from memory_extractor import LLMClient


# 按"更省token优先"排序：轻量模型排前面，作为主力；
# 更贵的模型放后面，只有前面的模型全部失败才会用到，起兜底作用
DEFAULT_MODEL_FALLBACK_CHAIN = [
    "doubao-seed-2-0-lite-260428",   # 轻量、性价比高，优先使用
    "deepseek-v4-flash-260425",       # 同样偏轻量的备选
    "doubao-seed-2-0-mini-260428",
    "deepseek-v4-pro-260425",
    "doubao-seed-2-1-turbo-260628",   # 推理型，token消耗大，放最后兜底
]


class AllModelsFailedError(Exception):
    """fallback链上所有模型都尝试失败后抛出，携带每个模型的失败原因方便排查。"""

    def __init__(self, attempts: list[dict]):
        self.attempts = attempts
        detail = "; ".join(f"{a['model']}: {a['error']}" for a in attempts)
        super().__init__(f"所有模型均调用失败: {detail}")


class ArkLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
        model_chain: list[str] = None,
        max_retries_per_model: int = 3,
        retry_backoff_seconds: float = 1.0,
        verbose_model_use: bool = False,
    ):
        from openai import OpenAI  # 延迟导入，跟AnthropicLLMClient的写法保持一致的风格

        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model_chain = model_chain or DEFAULT_MODEL_FALLBACK_CHAIN
        self.max_retries_per_model = max_retries_per_model
        self.retry_backoff_seconds = retry_backoff_seconds
        self.verbose_model_use = verbose_model_use
        # 【可观测性】记录每次成功调用实际是哪个模型回答的。
        # 之前的实现里，fallback链切换对上层完全透明——这样固然省心，
        # 但也意味着一旦某次回答行为反常，完全没办法确认"是不是这次
        # 恰好由链上某个风格不同的模型接手了"，这类差异会被误以为是
        # "同一个系统随机抽风"。现在把每次实际使用的模型记下来，
        # 事后能把"行为异常"和"当时是哪个模型在处理"对应起来看。
        self.usage_log: list[dict] = []

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        attempts_log = []

        for model in self.model_chain:
            for attempt in range(1, self.max_retries_per_model + 1):
                try:
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    )
                    content = response.choices[0].message.content
                    if content is None or content.strip() == "":
                        raise ValueError("模型返回了空内容")

                    self.usage_log.append(
                        {
                            "model": model,
                            "is_fallback": model != self.model_chain[0],
                            "attempt": attempt,
                        }
                    )
                    if self.verbose_model_use:
                        fallback_note = "（fallback）" if model != self.model_chain[0] else ""
                        print(f"    [model] 本次调用实际使用: {model}{fallback_note}")

                    return content
                except Exception as e:
                    attempts_log.append(
                        {"model": model, "attempt": attempt, "error": str(e)}
                    )
                    if attempt < self.max_retries_per_model:
                        # 指数退避：第1次失败等1秒，第2次等2秒……避免对故障中的服务连续猛敲
                        time.sleep(self.retry_backoff_seconds * attempt)
                    # 这个模型的重试次数用完了，循环会自然跳到 model_chain 的下一个模型

        raise AllModelsFailedError(attempts_log)


def load_env_file(path: str = ".env") -> None:
    """
    极简的 .env 加载器，不依赖额外的第三方包（python-dotenv）。
    只做一件事：把 .env 文件里的 KEY=VALUE 行，塞进 os.environ
   （已经存在的环境变量不覆盖，遵循"显式设置的环境变量优先"这个惯例）。
    找不到 .env 文件时静默跳过，不报错——因为很多环境是直接用系统环境变量的，
    没有 .env 文件是正常情况，不是异常。
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


if __name__ == "__main__":
    import sys

    load_env_file()  # 优先从 .env 文件读取（如果存在）

    # 优先用环境变量 ARK_API_KEY。命令行参数仍然保留作为备用方式，
    # 但会打印明确警告——因为命令行参数会明文出现在进程列表里
    # （比如 `ps aux` 能直接看到），不适合传密钥这种敏感信息，
    # 环境变量或 .env 文件不会有这个暴露面。
    api_key = os.environ.get("ARK_API_KEY")
    if not api_key and len(sys.argv) > 1:
        print("⚠️  警告：通过命令行参数传递API Key会明文出现在进程列表里（如 `ps aux`），")
        print("   不安全，建议改用环境变量 ARK_API_KEY 或 .env 文件。")
        api_key = sys.argv[1]

    if not api_key:
        print("用法: 设置环境变量 ARK_API_KEY，或在同目录下放一个 .env 文件（内容: ARK_API_KEY=你的key）")
        sys.exit(1)

    client = ArkLLMClient(api_key=api_key)

    # 简单测试：验证基本调用 + 能正确返回文本
    result = client.complete(
        system_prompt="你是一个简洁的助手，回答不超过20个字。",
        user_prompt="你好，请自我介绍一下",
    )
    print(f"模型返回: {result}")
