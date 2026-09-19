"""
llm_json_utils.py
------------------
真实LLM即使被明确要求"只输出JSON"，也经常会有一些"习惯性"的偏差，最常见的是：
  1. 把JSON包在markdown代码块里：```json\n[...]\n``` 或 ```\n[...]\n```
  2. 前后多了空白字符、换行

这个模块提供一个统一的、容错的JSON解析函数，全系统（extractor、retriever）共用，
解决"每个调用点各自处理一遍解析失败"的重复代码问题，也统一"解析失败时该怎么办"这件事。
"""

import json


def parse_llm_json(raw: str, on_failure_log: bool = True):
    """
    尝试从LLM的原始文本响应里解析出JSON。
    返回 (parsed_value, success: bool)。
    失败时 parsed_value 为 None，并且（默认）把原始文本打印出来——
    绝不能"静默"返回一个看起来合理但实际上是瞎猜的默认值（比如空列表），
    那样会把"解析失败"和"LLM正确判断没有结果"这两种完全不同的情况混为一谈，
    调用方无法区分，排查问题时会走很多弯路（就是我们这次实际遇到的情况）。
    """
    text = raw.strip()

    # 兼容markdown代码块包裹：```json ... ``` 或 ``` ... ```
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text), True
    except json.JSONDecodeError:
        if on_failure_log:
            print(f"    [警告] JSON解析失败，LLM原始返回内容如下（前300字符）：")
            print(f"    {raw[:300]!r}")
        return None, False
