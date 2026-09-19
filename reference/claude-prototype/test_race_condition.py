"""
test_race_condition.py
-----------------------
用两个真正独立的操作系统进程（不是线程），模拟"两个agent同时基于同一版本写入同一个文件"。

_debug_delay 参数人为地在"检查version"和"真正写入"之间插入0.5秒延迟，
把原本极短的竞态窗口人为放大到0.5秒，这样两个进程一定会在窗口期内碰头，
从而稳定复现问题（不加这个延迟的话，竞态是否发生取决于操作系统调度的运气，
不好用来做确定性测试）。

预期结果：
- 进程A：正常写入成功
- 进程B：应该拿到 VersionConflictError（因为它基于的版本，在它写入前已经被A改过）
- 不应该出现"B无视冲突直接把A的修改覆盖掉"的情况
"""

import multiprocessing
import time

from memory_store import MemoryStore, VersionConflictError


def worker(worker_name, path, content, if_version, result_queue):
    store = MemoryStore(base_dir="./memory_race_test")
    try:
        result = store.write(path, content, if_version=if_version, _debug_delay=0.5)
        result_queue.put((worker_name, "SUCCESS", result["content"]))
    except VersionConflictError as e:
        result_queue.put((worker_name, "CONFLICT_REJECTED", str(e)))


if __name__ == "__main__":
    import shutil
    from pathlib import Path

    shutil.rmtree("./memory_race_test", ignore_errors=True)

    # 先建好初始文件，两个worker都基于这同一个版本去写
    store = MemoryStore(base_dir="./memory_race_test")
    init = store.write("people/zhangsan.md", "张三：初始信息", if_version="new")
    shared_version = init["version"]
    print(f"初始版本: {shared_version}\n")

    result_queue = multiprocessing.Queue()

    p1 = multiprocessing.Process(
        target=worker,
        args=("进程A", "people/zhangsan.md", "张三：A写入的内容", shared_version, result_queue),
    )
    p2 = multiprocessing.Process(
        target=worker,
        args=("进程B", "people/zhangsan.md", "张三：B写入的内容", shared_version, result_queue),
    )

    p1.start()
    time.sleep(0.05)  # B 比 A 稍晚一点点启动，模拟真实场景里几乎但不完全同时
    p2.start()
    p1.join()
    p2.join()

    outcomes = []
    while not result_queue.empty():
        outcomes.append(result_queue.get())

    for name, status, detail in outcomes:
        print(f"{name}: {status}")
        print(f"  详情: {detail[:80]}\n")

    final = store.read("people/zhangsan.md")
    print(f"最终文件内容: {final['content']}")

    success_count = sum(1 for _, status, _ in outcomes if status == "SUCCESS")
    conflict_count = sum(1 for _, status, _ in outcomes if status == "CONFLICT_REJECTED")

    print(f"\n结果统计: {success_count} 个成功写入, {conflict_count} 个被拒绝")
    assert success_count == 1, "应该只有恰好一个进程写入成功！"
    assert conflict_count == 1, "应该有恰好一个进程被检测到冲突并拒绝！"
    print("✅ 测试通过：锁生效，没有发生静默覆盖，冲突被正确检测到")
