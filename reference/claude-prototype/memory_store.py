"""
memory_store.py
----------------
记忆系统的存储层：负责"记忆文件"的读、写、列出清单。

设计要点（对应我们聊过的几个知识点）：
1. version 用"内容的哈希值"来实现，而不是时间戳。
   为什么不用时间戳？因为时间戳的精度问题（两次写入间隔可能小于系统时钟精度）、
   以及"内容没变但时间戳变了"这种情况，都会导致误判。
   用内容 hash：只要内容真的没变，version 就不变；内容一变，version 必然变。
   这是最简单、最不会出错的"版本"实现方式。

2. write() 强制要求 if_version，这是"乐观锁"的核心：
   - 新文件：if_version 必须显式传 "new"（防止手滑覆盖已存在的文件）
   - 已存在文件：if_version 必须等于"你上次读到的那个版本"
     如果这期间文件被别的进程改过，版本对不上，直接拒绝写入并抛异常，
     把最新内容返回给调用方，让它自己决定怎么合并——而不是"后写的自动覆盖先写的"。

3. list_files() 返回的是"清单"，不是内容本身——
   这正是我们之前讲的"检索方法2（LLM推理路由）"要用的输入：
   LLM 先看清单做判断，判断完再决定读哪个文件的完整内容。

4. 【本版新增】摘要(summary)是独立维护的字段，不是从正文内容里"猜"出来的。
   早期实现里 preview 直接取"文件第一行"，这在文件只写过一次时没问题，
   但文件一旦被追加过内容（用户又提到了新事实），第一行还是最早那条，
   摘要就会过期、失真——这是用真实LLM测试时才实际暴露出来的问题：
   路由阶段完全基于这个"看似合理、实则过时"的摘要做判断，
   结果错过了本该匹配上的文件，而LLM的判断本身完全没有问题，
   问题出在喂给它的信息本身就是错的。
   现在改成：摘要以专门的一行（<!-- summary: ... -->）存在文件开头，
   跟正文内容分开维护，每次正文有实质更新，摘要要跟着重新生成，
   而不是每次都重新"猜"第一行。
"""

import contextlib
import fcntl
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Optional

SUMMARY_PATTERN = re.compile(r"^<!--\s*summary:\s*(.*?)\s*-->\s*$")


def format_summary_line(summary: str) -> str:
    return f"<!-- summary: {summary} -->"


class VersionConflictError(Exception):
    """写入时版本号对不上，说明文件在你读取之后被其他进程修改过。"""

    def __init__(self, path, expected_version, actual_version, current_content):
        self.path = path
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.current_content = current_content
        super().__init__(
            f"写入冲突: 文件 '{path}' 当前版本是 {actual_version}，"
            f"但你基于版本 {expected_version} 做的修改。"
            f"文件已被其他进程改过，请基于最新内容重新合并后再写入。"
        )


class MemoryStore:
    def __init__(self, base_dir: str = "./memory"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str) -> Path:
        # 统一走 base_dir，防止调用方传入 "../../etc/passwd" 这种越界路径
        full = (self.base_dir / path).resolve()
        if not str(full).startswith(str(self.base_dir.resolve())):
            raise ValueError(f"非法路径，超出存储根目录范围: {path}")
        return full

    @staticmethod
    def _hash_content(content: str) -> str:
        # 用内容的 sha256 前 12 位作为 version token
        # 12位足够避免碰撞，同时保持可读性（这个长度也是我自己这套系统实际用的长度）
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

    @contextlib.contextmanager
    def _lock(self, path: str):
        """
        跨进程文件锁，用来把"检查version + 写入"这两步包成一个原子区间。
        用的是操作系统级别的 flock（POSIX），不是 Python 线程锁——
        线程锁（threading.Lock）只在同一个进程内有效，
        但我们要防的是"两个完全独立的 agent 进程同时写同一个文件"，
        必须用操作系统提供的、跨进程都认的锁。

        锁文件本身是单独的 .lock 文件，不是记忆文件本体——
        这样即使锁文件存在，也不会污染 list_files() 读到的记忆内容。
        """
        full = self._full_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        lock_path = full.with_suffix(full.suffix + ".lock")
        with open(lock_path, "w") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)  # 排他锁，拿不到就阻塞等待
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def read(self, path: str) -> dict:
        """
        读取一个记忆文件。
        返回: {"content": str, "version": str | None}
        文件不存在时: {"content": "", "version": None}
        """
        full = self._full_path(path)
        if not full.exists():
            return {"content": "", "version": None}
        content = full.read_text(encoding="utf-8")
        return {"content": content, "version": self._hash_content(content)}

    def write(
        self, path: str, content: str, if_version: str = None, _debug_delay: float = 0
    ) -> dict:
        """
        整体覆盖写入一个记忆文件（乐观锁校验 + 跨进程互斥锁，二者结合防止TOCTOU竞态）。
        - 文件不存在: if_version 必须是 "new"，否则报错
        - 文件已存在: if_version 必须等于文件当前的真实 version，否则报错（写入冲突）

        _debug_delay: 仅用于测试，在"检查version"和"真正写入"之间人为插入延迟，
        故意放大竞态窗口，用来验证锁是否真的生效。生产代码不要用这个参数。
        """
        full = self._full_path(path)

        # 关键修复：把"检查version + 写入"整体包在锁里。
        # 拿到锁之后，任何其他进程的 write() 都会被 flock 阻塞在锁外面，
        # 必须等这次的 with 块结束（写完+释放锁）才能进来，
        # 这样就不存在"两边都检查通过，然后先后写入互相覆盖"的窗口了。
        with self._lock(path):
            exists = full.exists()

            if not exists:
                if if_version != "new":
                    raise ValueError(
                        f"文件 '{path}' 不存在，创建新文件请传 if_version='new'"
                    )
            else:
                current = self.read(path)
                if if_version != current["version"]:
                    raise VersionConflictError(
                        path=path,
                        expected_version=if_version,
                        actual_version=current["version"],
                        current_content=current["content"],
                    )

            if _debug_delay:
                time.sleep(_debug_delay)

            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            new_version = self._hash_content(content)
            return {"content": content, "version": new_version}

    def list_files(self) -> list[dict]:
        """
        列出所有记忆文件，返回清单（供检索路由使用）。
        每个条目包含：
        - path
        - preview：优先读取文件开头的独立摘要行（<!-- summary: ... -->），
          找不到时退回旧逻辑（取第一行非空正文），保持向后兼容
        - embedding：预留字段，当前恒为 None。
          现在规模下用LLM推理路由（方法2）就够用，不需要向量检索；
          但把这个字段现在就摆在数据结构里，是为了未来规模上去、
          要切换成向量检索（方法3）时，摘要的embedding可以缓存在这里，
          不需要改动 list_files() 的返回结构、不需要 retriever.py 跟着改接口，
          只需要在写入时把这个字段填上、在路由阶段多一步向量比对。
          这是一个明确的、低成本的"面向未来留缝"，不是过度设计——
          没有提前引入任何向量库依赖，只是保留了一个字段位置。
        """
        results = []
        for full in sorted(self.base_dir.rglob("*.md")):
            rel_path = str(full.relative_to(self.base_dir))
            content = full.read_text(encoding="utf-8")
            preview = ""

            first_line = content.splitlines()[0].strip() if content.splitlines() else ""
            summary_match = SUMMARY_PATTERN.match(first_line)
            if summary_match:
                preview = summary_match.group(1)
            else:
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and line != "---":
                        preview = line
                        break

            results.append({"path": rel_path, "preview": preview, "embedding": None})
        return results

    @staticmethod
    def extract_summary(content: str) -> Optional[str]:
        """
        提取内容开头的摘要行文本（如果有），不修改内容本身。
        返回摘要文本，没有摘要行则返回 None。

        必须在 strip_summary_line 剥离摘要行【之前】调用并保存结果——
        剥离之后文件里就不再有摘要行了，再想读"旧摘要是什么"就晚了
        （这正是我们实际踩过的一个时序bug：先剥离写入，之后再读文件想拿旧摘要，
          读到的已经是被剥过的版本，永远拿不到真正的旧摘要）。
        """
        lines = content.splitlines()
        if lines:
            match = SUMMARY_PATTERN.match(lines[0].strip())
            if match:
                return match.group(1)
        return None

    @staticmethod
    def strip_summary_line(content: str) -> str:
        """
        去掉内容开头的摘要行（如果有），返回纯正文，供重新生成摘要时使用。

        注意：这里用 splitlines(keepends=True) 而不是 splitlines()——
        普通 splitlines() 会把每行结尾的换行符也一并去掉，之后如果只用 "\\n".join()
        重新拼接，最后一行结尾的换行符就会丢失（尤其是只剩一行时，join单元素列表
        根本不会插入任何换行符），导致后续代码"以为body末尾有换行符就直接追加新行"，
        实际两条记录会被粘连成一行。keepends=True能保留原始换行符，
        拼接回去后内容跟原来完全一致（除了去掉的那一行）。
        """
        lines = content.splitlines(keepends=True)
        if lines and SUMMARY_PATTERN.match(lines[0].strip()):
            return "".join(lines[1:])
        return content


if __name__ == "__main__":
    # 一个最小的自测，验证三件事：正常写入、版本冲突检测、清单读取
    store = MemoryStore(base_dir="./memory_test")

    # 1. 创建新文件
    r1 = store.write("people/zhangsan.md", "张三是项目A的负责人", if_version="new")
    print("首次写入:", r1)

    # 2. 基于正确版本更新
    r2 = store.write(
        "people/zhangsan.md",
        "张三是项目A的负责人，联系方式 138xxxx",
        if_version=r1["version"],
    )
    print("正常更新:", r2)

    # 3. 模拟写入冲突：还拿着旧版本号去写
    try:
        store.write(
            "people/zhangsan.md",
            "一个基于过期版本的错误修改",
            if_version=r1["version"],  # 这是旧版本号，此时真实版本已经是 r2
        )
    except VersionConflictError as e:
        print("捕获到预期的冲突:", e)

    # 4. 清单
    store.write("projects/project_a.md", "项目A：状态进行中，截止日期10月", if_version="new")
    print("文件清单:", store.list_files())
