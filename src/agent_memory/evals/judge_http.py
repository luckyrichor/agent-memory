"""Provider transports for the whole-table judge pool. No text/credential logging."""

import json
from typing import Any

import httpx

from agent_memory.evals.judge_pool import Grade, Judge, JudgeFailure
from agent_memory.evals.model_policy import require_disabled_thinking


class ProviderJudgeRouter:
    """Choose each frozen judge's own cloud and credential, including on failover."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        prompt: str,
        tokens: dict[str, str],
        tokenhub_base: str = "https://tokenhub.tencentmaas.com/v1",
    ) -> None:
        self.transports = {
            provider: TokenHubJudge(client, token, endpoint, prompt)
            for provider, endpoint in {
                "TokenHub": tokenhub_base,
                "Ark": "https://ark.cn-beijing.volces.com/api/v3",
            }.items()
            if (token := tokens.get(provider))
        }

    async def __call__(self, judge: Judge, row: dict[str, Any]) -> Grade:
        transport = self.transports.get(judge.provider)
        if transport is None:
            raise JudgeFailure(401)
        return await transport(judge, row)


class TokenHubJudge:
    def __init__(self, client: httpx.AsyncClient, token: str, endpoint: str, prompt: str) -> None:
        self.client = client
        self._token = token
        self.endpoint = endpoint.rstrip("/")
        self.prompt = prompt

    async def __call__(self, judge: Judge, row: dict[str, Any]) -> Grade:
        # Deliberately omit table/group/system identity from judge input.
        content = {key: row[key] for key in ("question", "reference", "answer")}
        body: dict[str, Any] = {
            "model": judge.model,
            "temperature": 0,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": json.dumps(content, ensure_ascii=False)},
            ],
        }
        body.update(
            {"reasoning_effort": "none"}
            if judge.model == "hy3"
            else {"thinking": {"type": "disabled"}}
        )
        try:
            response = await self.client.post(
                self.endpoint + "/chat/completions",
                json=body,
                headers={"Authorization": "Bearer " + self._token},
            )
            if not response.is_success:
                raise JudgeFailure(response.status_code)
            data = response.json()
            require_disabled_thinking(data)
            grade = json.loads(data["choices"][0]["message"]["content"])
            if (
                set(grade) != {"correct", "reason_code"}
                or type(grade["correct"]) is not bool
                or grade["reason_code"] not in {"MATCH", "MISMATCH"}
            ):
                raise JudgeFailure()
            usage = {k: v for k, v in (data.get("usage") or {}).items() if isinstance(v, int)}
            return Grade(grade["correct"], data.get("model", ""), grade["reason_code"], usage)
        except JudgeFailure:
            raise
        except (
            httpx.HTTPError,
            ValueError,
            KeyError,
            RuntimeError,
            TypeError,
            IndexError,
        ) as error:
            raise JudgeFailure() from error
