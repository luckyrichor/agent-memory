# AGENTS.md

<!-- PHASE1_VENV_CLEANUP_20261103_START -->
- 2026-11-03T19:49—19:52+08:00（北京时间，date实测）用户授权清理阶段1标注/处理中间材料并删除本项目整个`.venv`，已执行并核验（实施CodeBuddy glm-5.3不回退；Codex已独立验收）。实施前核对：主机VM-0-15-ubuntu/ubuntu、HEAD `2f743d1`工作区干净、两目标真实目录无symlink逃逸（phase1内0个symlink；.venv仅4个标准内部解释器symlink，rmtree以lstat/unlink处理不跟随）、无独立挂载、无worktree（compat-1e2730c在.local根、source-B0在phase2均在目标外）。
- 删除前先复制最终保留物到`.local/phase1-final-kept/`（28文件，表观39,422,390 B）：按`docs/evals/phase1-acceptance-current.json`与`docs/reports/phase1-blind-adoption-2026-10-23/report.json`哈希引用精确识别——private_outputs 7（最终金标并集/人工投影/provenance）、inputs 12（final来源manifest/批次登记/adopted-old-pool/accepted-base）、protected 6（reviews与temporal ecd-owner报告），另按“小文件拿不准保留”例外复制上轮保留物normalized-v1（3文件）；复制SHA与源及report引用值全部一致。不复制整个旧目录，全部中间标签/响应/语料旧版未保留。
- 已删除：`.local/phase1/`整个目录（16,814文件，du块820,772,864 B、表观777,058,788 B，与manifest逐文件合计精确一致）与`.venv/`（4,644文件，du块144,003,072 B、表观130,605,833 B）；删除后两路径`[ -e ]`/`[ -L ]`均不存在。系统/共享解释器、其他项目环境、.local根（7个人工CSV、backups、compat-1e2730c、phase2、reports、ark.env）、docs/reports 417文件及.local根7份人工CSV、代码/pyproject/uv.lock、phase2结论、worktrees与容器卷全部未触碰。
- 核验：受保护424文件（docs/reports 417+根CSV 7）组合SHA256前后一致（`b671a449…`）；final-kept 28文件SHA前后一致；git工作区在文档更新前干净。空间`du -s -B1`仓库1,084,264,448→160,059,392 B，释放924,205,056 B（≈881.3 MiB，对账=820,772,864+144,003,072−39,518,208+清单gz约1,052,672 B精确自洽）。
- 最终状态：项目已结项，**不再可直接运行**——`.venv`已删，`uv sync --all-groups`可恢复依赖；阶段1原始材料已清，最终金标/人工确认/manifest仅存`.local/phase1-final-kept/`私有归档（不入Git）；原始中间数据、逐题调用缓存均已不可恢复，重跑需重新准备输入并可能产生费用。阶段1历史验收与阶段2未验收口径不变，服务保持停止。
- 本机审计（`.agent-tasks/`，经`.git/info/exclude`排除不入Git）：`2026-11-03-phase1-venv-cleanup.md`、`.py`、`-pre.json`、`-result.json`、`-phase1-manifest.jsonl.gz`、`-venv-manifest.jsonl.gz`。本轮仓库修改仅AGENTS.md与docs/progress.md，Codex独立核验通过：424份报告/人工CSV、7211份阶段2保留文件内容摘要均未变，28份归档逐项哈希一致（25份匹配既有报告来源哈希、3份匹配复制前清单）；交接随本次正常提交推送。飞书待同步：本次phase1/.venv清理；用户暂不写Wiki，未创建或修改飞书文档。
<!-- PHASE1_VENV_CLEANUP_20261103_END -->

<!-- NORMALIZED_TOOLS_CLEANUP_20261103_START -->
- 2026-11-03T19:38—19:40+08:00（北京时间，date实测）用户授权结项追加清理并已执行核验（result all_ok=true；实施CodeBuddy glm-5.3，Codex已独立验收）。实施前核对：主机VM-0-15-ubuntu/ubuntu、HEAD `78bb9f3`工作区干净、三目标均真实目录无symlink/独立挂载/越界。
- 已删除（逐文件哈希后执行）：`.local/phase1/normalized-v2/`（11文件）与`normalized-v3/`（11文件，两目录合计du块815,382,528 B≈777.7MiB，与用户预期约778MiB一致）及`.mypy_cache/`（3文件：.gitignore、CACHEDIR.TAG、3.12/cache.db）；删除后三路径`[ -e ]`/`[ -L ]`均不存在。25文件path/size/sha256/allocated清单（表观合计837,170,715 B）存`.agent-tasks/2026-11-03-normalized-tools-cleanup-manifest.jsonl.gz`（SHA256 `c6404274…`）。
- 已从本项目`.venv`完整卸载mypy 1.20.2与ruff 0.16.5两个发行包（`uv pip uninstall --python .venv/bin/python mypy ruff`，uv 0.12.17，exit 0）：importlib.metadata两者均PackageNotFoundError；`.venv/bin/{mypy,dmypy,mypyc,stubgen,stubtest,ruff}`与site-packages下`mypy/`、`mypyc/`、两个dist-info、`0aca9ce3…__mypyc…so`编译文件均不存在；`mypy_extensions` 1.1.0及其他包未动，`import agent_memory`正常。`pyproject.toml`/`uv.lock`声明保留，未来`uv sync`可重装；**验证卸载不要用`uv run`（会自动同步触发重装），须直接用`.venv/bin/python`**。
- 空间实测：`du -s -B1`仓库1,999,400,960→1,084,149,760 B（释放915,251,200 B≈872.7MiB，其中.venv释放78,000,128 B；=837,255,168+78,000,128−4,096，与两次测量间新增pre.json一个块精确对账）；`du -sb`释放911,540,756 B（=837,170,715+74,371,144−1,103，同样精确）。初始基线1,999,380,480 B与用户交接一致。
- 保留核验未动：normalized-v1（3文件）、.local根7个人工CSV（dulemon*/ecd*）、round3全部人工材料、docs/reports含closeout-2026-11-03全部旧报告与阶段2结论；受保护10文件集合内容摘要前后一致（SHA256 `81aa73da…`）；核验时点git工作区仍干净，未修改任何docs/reports文件便于按保留哈希校验。本轮不跑实验/模型/服务，不改变阶段2未验收状态。
- 本机审计（`.agent-tasks/`，经`.git/info/exclude`排除不入Git）：`2026-11-03-normalized-tools-cleanup.md`（实施前任务说明）、`.py`、`-manifest.jsonl.gz`、`-pre.json`、`-result.json`。本轮仓库修改仅AGENTS.md与docs/progress.md，Codex独立验收通过：424个报告与人工CSV的组合SHA256前后一致，卸载元数据与入口、删除路径均核验通过；交接记录随本次正常提交推送。飞书待同步：本次追加清理；用户暂不写Wiki，未创建或修改飞书文档。
<!-- NORMALIZED_TOOLS_CLEANUP_20261103_END -->

<!-- PROJECT_CLOSEOUT_20261103_START -->
- 2026-11-03T19:23:27.741025+08:00（北京时间）用户明确项目结项、不再继续；因CodeBuddy指定模型429配额超限，用户明确授权本次由Codex亲自归档与清理。
- 当前结项入口：`docs/reports/closeout-2026-11-03/结项补充.md`、`conclusions.json`、`staircase-trials.csv`、`cleanup-result.json`。补齐旧交付之后18个阶梯点及PerLTQA额度暂停（0结果行）；项目结项不等于阶段2验收通过，失败/未测/中断照实保留，不进入阶段3。
- 旧正式报告及ZIP/CSV/JSON原样保留；结项补测归档已先推送GitHub提交`6570a6c`，本次更新提交以Git历史为准。
- 清理完成：删除161520个清单内原始调用、阶段2逐题记录/检查点/映射/日志、项目内数据库dump及SQLite向量缓存，共释放5289734144字节（4.93GiB）；当前项目约1.86GiB，实际值见cleanup-result。
- 保留24328个本地文件的集合与内容摘要前后一致：阶段1数据/人工回填/标注、所有未列入删除清单的聚合报告与结论、配置/状态/环境元数据、源码worktree保留；Docker容器/卷、其他项目不动，agent-memory服务保持停止。
- 原始调用、逐题证据和部分数据库备份已删除，不能再依赖旧文档指向的这些文件进行完整重算/恢复；重新运行需新建输入/数据库并可能产生费用，不得自动恢复旧托管任务。前文关于“数据全部保留”的描述仅是历史状态。
- 本机审计：`.agent-tasks/2026-11-03-closeout-cleanup.md`、`2026-11-03-closeout-delete-manifest.jsonl.gz`、`2026-11-03-closeout-state.json`；均不入Git。`CLAUDE.md`保持仅引用本文件。
- 飞书待同步：2026-11-03项目结项与过程数据清理、补测结论；用户历史要求暂不写Wiki，未创建或修改飞书文档。
<!-- PROJECT_CLOSEOUT_20261103_END -->

<!-- SERVICE_STOP_HANDOFF_20261102_START -->
- 2026-11-02T15:08:37+08:00（北京时间）停服交接：用户明确要求停止 agent-memory 全部服务，本轮已执行并核对，本段优先于下文全部“正在运行”描述。
- 实际状态：本项目 API/worker 没有运行（无 agent_memory 进程、无自有 8000/8080/55432/13051 端口监听、无 agent-memory systemd 单元/计时器）。Docker 中 `agent-memory-b0-capacity-20261028` 已 `docker stop`，`agent-memory-postgres-1` 与两个 `agent-memory-b0-diskfull` 容器同为 Exited，所有 `agent-memory*` 前缀容器均不再运行，56432 端口已关闭。
- 容器、卷（`agent-memory_agent-memory-postgres`）、数据与 restart 策略全部保留，未删除任何文件或容器；本轮未改代码。属于 agent-ops-platform 的 `agent-ops-p7-memory`、`agent-ops-customer-memory.service` 及其他服务未触碰。
- 下文各段（含 `agent-memory-b0-*` 单元、扩展/容量测量、阶梯与 PerLTQA 等描述）中的“正在运行/等待/托管中”均为历史记录，不代表当前运行状态；恢复运行须等用户新指示，不得据本文件自行拉起服务或重跑测量。
- 版本核对：仓库 HEAD `53cba0f`（Document isolated customer-memory contract for Agent Ops P7），工作区已有未提交修改（含本文件、CLAUDE.md 及 97 项状态变更），本轮只改本文件、未提交未推送。
- 分工与凭据：本轮由 Codex 指导、CodeBuddy 实施，Codex 已独立验收：本项目进程与运行容器均为 0、56432 无监听；agent-ops-customer-memory 用户服务及其他应用服务仍 active；`CLAUDE.md` 仍只有 `@AGENTS.md` 一行，保持不动。
- 按用户历史约定暂不写 Wiki；**飞书待同步：2026-11-02 本次全部停服与保留数据交接**，原因同上，不是授权失效。
<!-- SERVICE_STOP_HANDOFF_20261102_END -->

<!-- STAGE1_VERIFY_20261103_START -->
- 2026-11-03T17:43:27+08:00（北京时间，现场读取）阶段1收尾**已完成**：代码修正已入 GitHub `6e87149`，A 类下载物清理已执行并核对，服务保持停止。实施 CodeBuddy（deepseek-v4.1-flash），Codex 已独立确认 8 条路径均不存在。
- 代码修正（已提交）：`src/agent_memory/evals/b0_selection.py` 的 `select_questions` 补类型注解；`tests/unit/evals/test_b0_selection.py` import 排序；`scripts/run-b0-mac-load.py`、`scripts/run-b0-linux-load-point.py` 去掉公网地址/派生主机名硬编码，目标改由 `--base-url/--host` 或 `B0_BASE_URL/B0_HOST` 提供，缺失时在 `mkdir` 前 `parser.error` 退出 2。
- 离线门禁（提交前跑过，本轮未重跑）：`pytest tests/unit` 409 passed；`ruff check src tests migrations` All checks passed；`mypy src` 102 文件无错；`git diff --check` 通过。未调用付费 API，未跑集成/容器测试。
- 清理**已执行**（用户授权）：删除 `.local` A 类 8 项共 487,069,042 B（464.5 MiB）——LongMemEval cleaned/oracle、DuLeMon.zip、ECD.zip、locomo/、PerLTQA/、k6 Linux 包、tokenizer.json。实测 `du -s -B1` 仓库 7,769,567,232 → 7,281,754,112 B（约 7.24 → 6.78 GiB），`du -sb` 7,216,173,816 → 6,729,104,774 B；表观差值与该 8 项总字节完全一致。清单与哈希存 `.agent-tasks/2026-11-03-cleanup-result.json`，私有、不入库不上传。
- 可再下载来源仍按 README 与旧下载清单重取，未新增下载说明文件；冻结 `normalized-v3`、旧归一化产物、付费模型输出、人工标签、向量、DB dump、worktrees 与容器卷全部保留，容器/卷/restart 策略未动，服务与进程仍全部停止，未启停任何单元。
- 版本状态：HEAD `6e87149`（Sync stage-1 B0 evidence, measurement tooling and handoff docs）已推送 GitHub origin/main；`CLAUDE.md` 仍只有 `@AGENTS.md` 一行，保持不动。阶段2 仍未验收、未进入阶段3。
- 飞书 Wiki 按用户要求仍暂缓；**飞书待同步：2026-11-03 阶段1 收尾完成与 A 类清理结果**，原因是用户明确暂不写，不是授权失效。
<!-- STAGE1_VERIFY_20261103_END -->

<!-- B0_EXPANSION_20261101_START -->
- 2026-11-01T17:18:08.358941+08:00 负责人已核对上一聚合报告无误，授权阶段2再补一轮并再次要求继续，仍不进入阶段3。本段优先于下文历史进度。
- 实际运行：agent-memory-b0-rate-staircase-v2-20261101.service，搜索/context×10k×0.1/0.25/0.5QPS×3轮；控制器scripts/run-b0-rate-staircase.py；私有日志/检查点.local/phase2/b0/expansion-20261101/。当前第1点恢复轮实际200，不能提前称稳定通过。
- 原stair-search-01首轮在TX主机重启前中断，远端完整证据已迁回；30测量请求14错误、0drop，目标机监控内存峰值97%并有probe失败。重启/内存压力原因未确定，不作系统容量结论，单列interrupted-point.json。重启后新boot_id151b2eb9-3250-4069-aae6-870e90ee843c，自有DB重新启动并用host nsenter恢复shm512MiB。未影响其他业务容器。
- v2新标签stair2-*不覆盖旧结果；增加目标主机80%内存保护，目标主机资源超过70%不作稳定容量结论；发压端仍70%约束。结束只清自有API/Nginx入口，不修改B0业务。
- 后续实际托管单元agent-memory-b0-expansion-continuation-20261101.service正在等阶梯18点测完；只有序列完成才运行PerLTQA300题×四组×两模式×3次，固定GLM主裁判无fallback，避免与压测同时争用本机资源。配置config-perltqa300-private.json、预算账budget-ledger.json；旧lineage向量已用13051，本批硬上限24990，合计38041<=原66293；未增加原总上限。厂商额度/型号变化/预算到顶即暂停，不自动进阶段3，不自动发未完成报告。
- 其余扩样已选定冻结dev ID：中文质量150题/102会话、LongMemEval每子集50题；连同PerLTQA共550题向量估算696060，含25%余量870075。其余批次等待预算选择；LoCoMo冻结dev只有3会话，等待保留3并列例外或补2新dev会话的选择，不能挪测试。
- 仅测量层增加池队列等待/物理建连计时；真实单池饱和校验约121ms等待。小数k6速率inspect确认1次/10s；ID选题防止非dev、重复、错会话、流程题混入；选题签名纳入恢复校验，13相关测试通过。业务source-B0未改且干净，无提交推送。
- 计划/预算/9项例外位于docs/reports/phase2-b0-expansion-2026-11-01/；新完成报告尚未出，旧交付包不覆盖。Wiki待同步：本轮扩样预算、重启中断证据、阶梯恢复与自动后续；用户暂不写Wiki。
- 2026-11-01T17:24:18.091519+08:00 v2已完成1/18点：搜索0.1QPS第1轮31测量请求0错误0drop，remote k6_exit0、发压机CPU峰12.1%/内存24.1%、目标机内存峰36.1%。SSH控制退出255但远端status/summary/resources/log独立回收核对；保留control_exit，不把它改成0。
- 该点客户端p95约26.24s，服务端词法SQLp95约26.06s、向量0.127s、结构化0.016s，池blocking get0次；初步定位尾耗时落在词法SQL，不能称已证明唯一根因或稳定最大速率。原始阶段统计含预热，后续还需测量窗口分析。当前第2轮仍实际运行。
- 监控等待/SSH回收使单点约466s，当前自有阶梯unit运行上限已通过runtime drop-in调整3h；不改变测量6分钟窗口。后续等待单元已重新启动并将等待上限增至11000s，仍等18点结束后再开PerLTQA，避免资源干扰。4份提示词SHA均与旧运行manifest一致，run-b0启动时会再次严格核对。
<!-- B0_EXPANSION_20261101_END -->

<!-- B0_REPORT_DELIVERY_START -->
- 2026-11-01T09:26:11.240894+08:00 本轮报告收尾已实际完成并发群，不再等待上传：正文消息om_x100b615d1e7378a8cff7688457cc147，ZIP消息om_x100b615d1e1900acb013c78c46ec173。最新索引docs/reports/B0-aggregate-latest.md，正文docs/reports/b0-aggregate-20261101-092435/B0-report.md；ZIP SHA256 899250cefcdfb706d45c2b5a87eab296728f6367ebb5575d21d68f7aaf7356d0。
- 交付含40个四系统/两模式质量表、372条总体指标、752条题型指标、18轮公网测量及资源/区间、QA300/抽取73校准、66项覆盖、匿名失败案例、故障与恢复。1272质量行与288流程行分开，Chinese数据内B类题不误作全部流程。
- 全18轮日志复核：完整虚构查询正文117次（首6轮58次）；已配置且能获取的APIkey0命中。原文/人工标签理由/凭据不入包。文件哈希/ZIP/分母/隐私检查通过，7相关单测通过；B0冻结源仍干净。
- report_document_finalized与report_delivered=true；measurement_coverage_complete、phase2_accepted、full_aggregate_ready均false，stage3_started=false。报告内明确已测/局部/未测：{'已测（限定范围）': 27, '局部观察': 19, '未测': 20}。原始全覆盖自动交付闸门未擅自解除；本次交付按用户“标通过/失败/未测并汇总发群→开始吧”授权范围完成。
- 接手先读最新索引和本地aggregate/current-state.json；旧report.json是冻结数值来源，旧“校准待办/未开始PF”文字属历史，不得当当前状态。剩余缺口明确保留，不把报告已发解释为验收通过或进入修复阶段。
- 本轮未提交/推送，工具来源agent-memory@53cba0f含未提交修改；Wiki按用户暂不写，飞书开发记录待同步：本轮最终汇总和交付。
<!-- B0_REPORT_DELIVERY_END -->

<!-- B0_ACTIVE_REMAINING_START -->
- 2026-10-31T16:29:36.827133+08:00 不再等待负责人催促：后续公网write/context序列已实际启动，单元agent-memory-tx2-extra-sequence-20261031.service，最长6600秒；12/12点现已完成并核对，单元退出0、自有入口已关闭。写入测量1805请求0错误，2165确认写入全在；context10k失败561/867、100k865/888，两端负载机资源合格。计划write/context×10k/100k×3次，共12点，每点60s预热+300s测量与两端采样，预计约80余分钟，完成仅指此批测量，不表示性能通过或阶段2全覆盖。
- 控制脚本scripts/run-b0-tx2-extra.py；私有日志capacity/tx2-extra-sequence.log，逐点检查点tx2-extra-sequence-private.json；最终聚合tx2-extra-public-load.json，自动清本任务API/自有Nginx入口并调用报告/交接收尾。异常/资源超限即保留证据并停，不自行修B0。每轮新克隆，原始10k/100k种子不写入；已实际烟测write201、context200。
- write请求只用完全虚构32字文本、精确预计算腾讯原生向量；0厂商模型调用。记录客户端确认写入ID并核对存在，真实worker入库队列耗时只代表DB入队到完成；待完成jobs删失，不能冒称客户端公网可见新鲜度。原query/reader实验源码已归档load-tools/read-*-used.*，不覆盖旧结果。
- 本轮故障补齐已完成：F12 now依赖±120秒6次成功（不改OS时钟），F6默认30秒租约实际等待3次晚到向量提交均拒绝；F2占满原生15连接3次均约30s/HTTP500，快速可重试失败未通过。搜索503/429/超时各3次实际HTTP夹具收到1次请求后降级200/零vector通道，超时实际约3s，见search-degradation-verified.json；旧缺fixture token的观测已标无效，不采纳。
- F9独立16MiB tmpfs tablespace真实满3次，API500且捕获SQLSTATE53100；读200/清理后写201/确认写入无丢失，错误语义不合格。第一版遇422不证明磁盘满，已单列disk-full-unverified-v1.json，不能冒称通过。独立新容器已停止，无主机磁盘写满。
- F4冻结adapter24次边界观测（21次非法/越权/超长/敏感输出阻断或回退，3次指令文字可成为unverified候选但不能改scope/authority），不声称整条DB持久化验证。冻结B0原有全套234tests通过17.80秒，源worktree仍干净。仅后台测量脚本改动，工具来源agent-memory@53cba0f含未提交修改，无自行提交。
- F10变更向量型号与当前固定型号约束冲突，未擅自换型号；F11无新的业务迁移目标，未伪造结构变更；这两项仅明确缺口，不偷改验收。更全面PF网格/跨地域链路仍未测。完整文件门保持false，不进入阶段3；Wiki按用户暂不写。
<!-- B0_ACTIVE_REMAINING_END -->

<!-- B0_EXTRACTION_OWNER_START -->
- 2026-10-31T15:54:33.137888+08:00 负责人已回传extraction-owner-review-private_filled.csv（消息om_x100b616daf13a8b4c135662086ec5e6）。73行完整唯一匹配，question/reference/answer零修改，判定0/1与理由全有效；原件600权限私有保留，SHA见extraction-owner-calibration.json。
- 专项校准通过：GLM73条accuracy94.52%/κ0.88567，MiniMax95.89%/κ0.91482；precision43与recall30分别也过κ>=0.7或accuracy>=90%门槛。无需仅为通过门槛修订提示词或重复调用模型。
- 人工抽取指标（DuLeMon冻结dev8会话×3次）：EX1=21/43=48.84%，95%会话簇区间[20.00%,72.22%]；EX2=7/30=23.33%，区间[0,48.15%]；F1=0.315789。不能外推完整dev/test，不把此前模型诊断值当人工结果。
- EX5独立归属错误子标签及抽取裁判重复稳定性未由本73条覆盖；QA稳定性不得替代。本次仅聚合数字进入公开报告，标签/理由/对话仅服务器私有目录。73条人工复核缺口已关闭，其他故障/PF覆盖仍缺；完整报告未放行，不进阶段3。
- 已更新本地B0报告；本次工具agent-memory@53cba0f含未提交修改，业务B0@1e9d6f3不变。编译/4个相关校准及交付门单测/diff通过，无新增模型调用，Wiki按用户要求暂不写。
<!-- B0_EXTRACTION_OWNER_END -->

<!-- B0_LATEST_AUDIT_START -->
- 2026-10-31T15:36:32.752087+08:00 最新人工核对：TX2全部6轮完成，压测API/发压进程无存活，自有Nginx入口已移除。100k恢复通过。
- 性能未通过：1QPS下10k失败557/867=64.24%，100k869/888=97.86%，p95约30秒，各轮丢弃11（共66）。发压端资源均合格；词法SQL慢/连接池超时仅为症状证据，不声称已证明单一根因。跨公网独立主机，不是跨地域（两台上海）。
- SC4确认失败：取消查询异常中的SQL参数带出完整虚构查询正文58次；所检查API密钥0命中。不得再用早期两个成功/422场景0泄漏宣称SC4通过。详见tx2-results-audit.json/md和log-leak-check.json。
- 已更新本地B0聚合delivery.md补齐核验段；full_aggregate_ready仍false，未发完整最终文件、未进阶段3。73条抽取盲审CSV及说明已按负责人明确授权发群（文件消息om_x100b616d81e1b8a4cf080fa11685d1e，73行SHA保持不变），待填写human_correct/human_reason；人工结果回收后仅服务器私有处理。其余故障/PF覆盖仍缺。原始负载日志已迁回TX私有目录（tx2-load-generator-private），TX2不保留唯一副本。
- 核验代码来源agent-memory@53cba0f加未提交修改，业务B0@1e9d6f3不变且干净；本次未自行提交/推送。Wiki依用户暂不写继续待同步。
<!-- B0_LATEST_AUDIT_END -->

<!-- B0_CAPACITY_SEQUENCE_START -->
- 2026-11-01T09:10:40.303775+08:00 TX2托管容量测量状态：measurements_complete，已收集12/12点；实际结果与有效性见docs/reports/phase2-b0-completion-2026-10-28/tx2-public-load.json。
- 本托管程序已尝试清理自有API与临时Nginx入口，接手者应核对服务和入口确已关闭；失败记录保留。
- 本记录不表示阶段2全部完成：抽取专项人工校准、其余PF/故障覆盖、跨地域链路等缺口仍须核对；完整报告未放行，未进入阶段3，Wiki按用户暂缓。
<!-- B0_CAPACITY_SEQUENCE_END -->

## 当前交接状态（2026-10-26T17:51:51.263543+08:00；优先于下文历史记录）

<!-- B0_RUN_STATE_START -->
- 2026-10-30T13:32:28.217645+08:00 阶段2仍未完成，未进入阶段3，full_aggregate_ready=false，完整文件继续延期；用户暂不写Wiki。
- 新B01560答题判分、QA300人工校准和两裁判100×3稳定性已完成。100k真实腾讯原生向量及100k种子库全部完成；答题/抽取固定官网deepseek-v4-pro，向量固定kinfra-text-embedding-0.6b1024，禁止Ark；凭据只经私有helper取，禁止日志/报告出现密钥。
- RL6跨Mac恢复已通过：484088060字节备份SHA一致，恢复9.40秒，全部表/1000随机行/32检索/RLS/角色相等；Mac原生PG已停。源/目标pgvector0.8.6/0.8.7差异及源共享内存64->512MiB修正均记录recovery100k.json。
- F3持续HTTP503失败补测已完成：三次均原生max_attempts5、真实退避后进入dead；证据provider-exhaustion.json，初版污染库导致的夹具断言失败保留，正式结果来自干净独立克隆。搜索降级语义和其余故障覆盖仍待做。
- F5真实进程死亡3次通过（默认30秒租约、约31秒接手，向量版本1行）；F3真实HTTP超时/429/503各3次退避恢复通过（持续失败/死信/降级仍未全覆盖）。F1实际API压力下数据库重启3次，120确认写入全在，14个HTTP500、12传输失败；错误语义缺陷保留，不整体称通过。
- 官方tokenizer390上下文/8usage差分均0。EX语义仍待73条专项人工校准（私有completion-20261028/extraction-v2/extraction-owner-review-private.csv），不能借QA κ放行。负责人已明确要求将待判定内容发群；73条表和说明已实际成功发送，等待回填。
- Mac公网10k/1QPS第一轮无效：初始内存74.8%，峰值82.9%，CPU峰值98.2%；测量289请求/178失败/11丢弃。已停后续Mac发压，保留public-load.json，不据此称系统容量。Mac可正常使用/休眠，不能再次未经必要性让其发压。
- 切至用户授权TX2独立负载机，已实核VM-4-5-ubuntu、ubuntu、2核、1967MiB，初始约23%内存；无常驻业务。临时目录~/project/agent-memory-b0-load-private，只传全虚构128查询/原生向量/短期隔离JWT，不传真实对话、人工标签或厂商APIkey。工具官方k6v2.3.0Linux包30847764B，SHA39c3117b6af817592dcd0ce4242105c0a7af10948c2a425306f0be8f7a8a8ab1已与官方核对，SCP安装与SHA复核完成，实测k6v2.3.0/e088784614/go1.26.8。TX2真实HTTPS检索烟测200后已开始正式托管发压。
- 已准备run-b0-tx2-capacity.py托管监督：10k/100k各1QPS×3轮，每轮60秒预热+300秒测量，两端资源，独立API进程并清空上一轮本应用会话；固定同一128虚构查询。只测读取search点，不冒称完整PF网格/写入context/最大容量。启动前已完成安装、限源49.234.33.103实测匹配、烟测和统一独立容器shm512MiB；CPU2/mem3GiB不变。实际单元agent-memory-tx2-capacity-sequence-20261030.service（最大3300秒），日志capacity/tx2-sequence.log，检查点capacity/tx2-sequence-private.json；目前第1轮运行，不能当完成。脚本结束自动关自有API/移除自有Nginx虚拟主机/写聚合局部报告，始终不自动放行阶段2或发不完整报告。
- 当前由托管程序启动独立测试API，Nginx自有虚拟主机限源TX2；两台IMDS地域均ap-shanghai，只证明独立主机跨公网，不宣称跨地域测量。结束清除自身文件并reload。不得影响其他服务。
- 主代码B0@1e9d6f3干净；根HEAD2fae08b及未提交测量脚本，未提交/推送。7个交付门/校准/补充证据单测通过，新增脚本py_compile与diff检查通过。证据docs/reports/phase2-b0-completion-2026-10-28/；私有.local/phase2/b0/completion-20261028/。Wiki待同步：本次全部补齐进展（用户明确暂不写）。
<!-- B0_RUN_STATE_END -->

- 项目：企业级跨会话记忆服务；Python3.12/FastAPI/SQLAlchemy/PostgreSQL+pgvector。阶段1已验收，当前仅阶段2测量，不优化业务、不进阶段3；阶段1数据/切分保持冻结。
- 最新方案原件`docs/plans/2026-10-26-agent-memory-interview-plan-v4.md`，928行已完整读；比上版新增8行权威角色调整，保留原作者。用户最新消息ID`om_x100b62c56df1b8b0ce44568e5c1acc0`覆盖此前同系列混用/方舟/DeepSeek后备规则。
- B0业务源码标签不变，`B0@1e9d6f3`；实际加载`.local/phase2/b0/source-B0`。新的结果配置身份`B0-deepseek-v4-pro-kinfra-20261026-v1`，配置`docs/baselines/b0/config-frozen-deepseek-v1.json`，策略`docs/evals/b0-policy-v7.json`。
- 答题/运行抽取固定同一个官网`deepseek-v4-pro`：温度0、关闭思考、5标签一致、100格式全过及原生角色实测已通过。任何其他答题/抽取型号、观察到的响应ID变化均不采纳，不再同系列拼接。
- 方舟真实请求禁止；腾讯原生1024维`kinfra-text-embedding-0.6b`，新库从输入重算、不复用旧Ark向量。不传该服务不支持的dimensions参数，不裁向量凑维度，不自动换向量模型。向量原生106检查/100格式有效；浮点逐元素一致不是裁判5次标签一致门槛。
- 主裁判GLM5.2，备选MiniMax3，均TokenHub新预检通过。每对比表单一裁判，备选整表重判；MiniMax标注的中文构造表排除MiniMax裁判。MiMo两已配Key均402，整批交叉参照暂用合格MiniMax；若采样裁判同型号则不冒称独立，单列缺口。
- 必须写入每份报告的局限：DeepSeek同时是金标准标注模型之一，抽取/答题与标注同厂商可能使抽取指标略偏高；双厂商共同保留已部分抵消。O10因Ark无额度不做新公平对照；旧Ark数据仅探索参考，不算新B0优化收益。
- 旧全链路零分已只读逐会话核查：6640记忆均有映射但active为0，主因是候选被状态过滤；111个会话×重复单元中2个无产出、109个被过滤；失败/回退尝试241/6484单列。**不偷偷激活候选或修改B0检索。** 每个新单元记录候选/active/映射/返回/向量入库，证据在`docs/reports/phase2-b0-rebuild-2026-10-26/fullchain-zero-diagnosis.json`。
- 候选确认补充核查：`B0-CANDIDATE-ACTIVATION-MISSING`，冻结B0没有原候选转active的正式公开路径；restore仅归档恢复，显式写入创建新ID。未追加确认后测量（null/不适用），不改业务或数据库状态；审计脚本和哈希证据见`candidate-confirmation-audit.json`。当前进程未停止/重启，新校准表仍整组完成后生成。
- 小样两模式×3次×4组完成24行，答题/判分均有效；187次调用，仅DeepSeek/TokenHub，无旧向量重放。原生重建观察显示直写active、全链路candidate，均已落腾讯向量。整组固定开发抽样规划1560实验行，不是全部开发集。
- 向量预算53034次加25%余量13259，本轮上限66293；预检/小样另列。是规划上限，不是余额查询或供应商已锁定额度。向量耗尽、预算耗尽或固定版本漂移暂停；服务不自动换其他模型。全新300种子`2026102601`，每行ID带本配置身份，旧表不能用于本次κ。
- 发布检查460 passed in45.79s，ruff/strict mypy/foundation通过；覆盖网络前禁止Ark、固定响应版本、预算阻止额外HTTP、旧表禁采纳、自动收尾不覆盖新运行/他人文字。来源基于2fae08b加未提交修改，本轮未自行提交或推送，私有源码快照哈希已留证据。
- 单一实际入口见执行报告；`scripts/start-b0-managed.py`启动后`managed-b0-execution.py`运行`run-b0.py`，完整后自动`summary`和本地交接收尾、发本群聚合文件；CSV仍只服务器。`scripts/record-frozen-b0-handoff.py`仅在当前运行身份/路径匹配时改上述动态状态块并追加开发记录，不写Wiki。
- 下一步：让唯一托管任务完成；检查原始usage与version/budget暂停文件；新300表生成后交负责人，按实际裁判分别校准κ/准确率/混淆矩阵，负责人最新300条校准指令已明确改为κ≥0.7或准确率≥90%，最多3轮，仍未达标则该指标纯人工（替代此前κ单闸门），也不能用一个κ替未覆盖备选放行。100条3次稳定性、缺失功能观察适配器、独立跨地域Linux发压机/PF仍未完成，不进入阶段3。
- 快速检查：`systemctl --user show agent-memory-b0-frozen-20261026-v1.service -p ActiveState -p SubState -p MainPID`；完整本机回归`bash scripts/check.sh`。启动命令已执行，勿重复起同一组；原始数据/对话/答案/校准/密钥均不进Git或公开报告。新配置正确性摘要必须来自本轮correctness-observations.json；缺失就未测，不借用旧全局摘要。
- 关键文件：新配置约束`src/agent_memory/evals/b0_frozen.py`；诊断`diagnose-b0-fullchain.py`；预算/历史排除`prepare-frozen-b0.py`；小样/预检证明`report-frozen-b0-readiness.py`；报告`report-frozen-b0-execution.py`。指标数据、报告、manifest与哈希见`docs/reports/phase2-b0-rebuild-2026-10-26/`；详细开发记录`docs/devlog/2026-10-26-phase2-b0-frozen-deepseek-rebuild.md`。
- 飞书只读核对：我的文档库/WorkPlan/agent-memory：Agent长期记忆服务，节点XQZgwJseiieKvpk6HWqcBOACnFg，无子节点。已提出用户本人--as user/profile codex同步三篇（项目概览/开发记录/B0模型配置与诊断报告）的标题范围位置方案，用户已明确暂不写飞书，没有发布。**飞书待同步：2026-10-26 新方案差异、预诊断、预检/预算/重建启动；原因是用户明确要求暂不写飞书，不是登录授权失效。**

以下保留原作者的历史背景与基础约定；模型角色和阶段状态以本节与当前policy为准。

最后更新：2026-10-08（北京时间）

本文件为在本仓库工作的编码 agent 提供指引（Claude Code 读 `CLAUDE.md`、Codex 读 `AGENTS.md`，两者都指向这里）。

## 这是什么

企业级 Agent 跨会话记忆系统。它同时是求职计划里**项目 ④（对应岗位 01：腾讯 AI 记忆系统研发专家）**的载体，总计划见 `luckyrichor/workplan-docs`。

仓库有两部分，边界必须清楚：

- **`src/agent_memory/`** —— 本项目本体，构建/测试/发布的全部范围。
- **`reference/claude-prototype/`** —— 外部参考原型，另一套独立实现，**不参与构建、不可 import**，只作为 Phase 3–5 的设计输入。详见 `reference/README.md`。

## 环境与命令

Python 3.12（`uv` 管理），PostgreSQL 走 Docker，本机不装数据库。

```bash
uv sync --all-groups              # 重建 .venv（约 150M，可随时删了重建）
docker compose up -d postgres     # pgvector/pgvector:pg16，端口 55432
uv run alembic upgrade head
```

发布门（四条都要过）：

```bash
uv run pytest -v
uv run ruff check src tests migrations
uv run mypy src                   # strict 模式
uv run python -m agent_memory.evals.foundation_runner
```

跑单个测试：

```bash
uv run pytest tests/unit/domain/test_jobs.py::test_claim_rejects_active_lease -v
uv run pytest tests/unit -q       # 只跑不依赖 Docker 的部分
```

Worker（完整参数见 README）：

```bash
uv run python -m agent_memory.workers.extraction dispatch --tenant-id <uuid> --once
uv run python -m agent_memory.workers.extraction work --tenant-id <uuid> --worker-id w1 --once
```

**`tests/api` `tests/integration` `tests/e2e` 走 Testcontainers**，Docker daemon 不可用时会直接抛 `DockerException` 而不是跳过 —— 那是环境问题不是代码问题。

**Docker 默认跑在 `tx` 服务器上**（见下方「Docker 运行位置」）。tx 上 Postgres 已常驻，`ubuntu` 已加入 docker 组，Testcontainers 可直接使用。

### 基线状态（2026-09-20 在 tx 上完整验证）

| 门 | 结果 |
|---|---|
| `uv run pytest` | **103 passed**（含 Testcontainers 测试；2026-09-19 基线为 75） |
| `uv run ruff check src tests migrations` | All checks passed |
| `uv run mypy src`（strict） | 47 文件无错 |
| `evals.foundation_runner` | 8/8，0 租户泄漏，0 删除命中 |
| `alembic upgrade head` | 三条迁移全部成功 |

这是**完整**基线，不是「除了需要 Docker 的部分」。已验证的包括：RLS 跨租户隔离（已知 ID 攻击）、迁移建表与 pgvector 扩展、Postgres 仓储与内存仓储行为一致、Event 摄取的原子性与幂等、Outbox 派发幂等、Job 租约防抢占与过期恢复、API 的 JWT 租户绑定与版本生命周期、Event→Evidence→MemoryVersion 完整血缘。

**在此基础上改动后，四道门都要重新跑过再提交。**

**测试必须跑全量，不能只跑改动相关的那几个文件。** M1 期间踩到过一次：单文件跑通、全量跑挂，原因是 alembic 迁移会影响 logging 状态，而单跑时迁移根本没执行。

## 架构：六边形分层，依赖单向朝内

```
api/          FastAPI 路由、JWT 认证、错误映射
  ↓
application/  用例服务 + Protocol 定义的端口（ports.py / event_ports.py）
  ↓
domain/       纯领域对象，frozen dataclass，零 I/O 零框架依赖
  ↑
infrastructure/  端口的适配器：SQLAlchemy 仓储 + 内存仓储（两套实现同一组 Protocol）
workers/      CLI 入口，把 application 的服务接到长驻循环上
evals/        用内存适配器跑的场景评估，不碰数据库
```

`observability/` 是**叶子包**：不 import 其他层（只 import `config`），所以每层都能用它而不产生环。日志、span、指标三条通路共用同一份字段白名单。理由见 `docs/design-decisions.md` 的 D1、D2。

`infrastructure/in_memory*.py` 与 `repositories.py` / `event_repositories.py` 是同一批 Protocol 的两套实现 —— 这是单测和 evals 能秒跑、只有集成测试才需要 Docker 的原因。**加新用例时先在 `application/*_ports.py` 定义 Protocol，两套适配器都要实现**，否则 evals 会掉队。

## 核心不变量（改代码时不能破坏）

- **租户身份只来自 JWT**。请求体里出现 `tenant_id` 一律拒绝。API 连接**不得**使用数据库 owner，因为 owner 绕过 RLS；迁移里建了 `agent_memory_app` 角色（`NOSUPERUSER NOBYPASSRLS`）。
- **PostgreSQL 强制 RLS**：每张表 `ENABLE` + `FORCE ROW LEVEL SECURITY`。
- **记忆版本不可覆盖**。纠正走 `POST /versions` 追加新版本，`expected_revision` 做乐观并发。删除是逻辑删除；状态机 8 态，`deleted` 是终态。
- **Event 不可变**，`(tenant_id, idempotency_key)` 幂等；同键不同内容、或同 session 重复 sequence，都返回稳定 409。
- **Event 与 Outbox 同事务落库**，再由 dispatcher 幂等转 Job。Job 30 秒租约、指数退避上限 300 秒、5 次后进 `dead`。
- **候选记忆不得扩大 scope**：`ExtractionWorker` 显式检查 `candidate.scope != event.draft.scope` 并判为不可重试失败。
- **日志和 CLI 输出不得包含 Event 正文或记忆正文**，只输出计数、ID、结果和原因码。这条已经由 `observability/fields.py` 的字段白名单强制：白名单里没有任何能放正文的字段名，越界即抛 `UnsafeTelemetryField`。**要加新字段就改那个文件**，不要绕过 `StructuredLogger` 直接用 `logging`。
- 高风险组合（procedural + tenant scope + 无 `memory:admin`）自动落到 `needs_review` 而非 `active`。

## 已实现 vs 未实现

**不要把未实现的说成已完成**，README「当前边界」一节是权威口径。

已有 —— 可观测性地基、三类记忆、四类 scope、JWT + 权限 + RLS、幂等创建、乐观并发、不可覆盖版本、生命周期、审计、embedding worker、三路混合检索与分页、Event/Outbox/Job/Evidence 链路。M4 的 API/融合/模型配置和验收边界见 docs/retrieval.md；真实模型5条语义改写验收已通过；生产规模质量评估未做。

未有 —— 见下方路线。

## 开发路线（Phase 3–5）

设计依据是 `docs/superpowers/specs/2026-08-30-enterprise-agent-memory-system-design.md`，改架构前先读第 19 节阶段划分和第 20 节的 10 条验收标准。

**第一梯队**（岗位 01 直接考 + 被 `agent-ops-platform` 依赖）

- **混合检索**：PG 全文 + pgvector 向量 + 结构化过滤三路候选，可解释融合与重排。含 **embedding worker**（M3 已有生成/落库/重建/重试管道，真实模型语义改写初验通过，生产规模质量评估未做）。
- **Context Builder + Token 预算**：M6已实现API/SDK与可测试预算裁剪，保守UTF8计数及证据/冲突边界见docs/context-builder.md。
- **可观测性**：M1 已完成地基 —— 全链路 trace、JSON 结构化日志、四个基础指标（2026-09-20）。**未完成**：没接任何后端（只有 console 导出器，无 OTLP／采样／告警／看板），spec 第 17 节的四层评测仍然全空。
- **基线对比评测**：spec 验收标准第 10 条要求对比 No Memory 和 Naive Vector 两条基线，未实现。
- **Python SDK**：M2 已实现 HTTP SDK；`agent-ops-platform` 要调用本服务。

- **真实 LLM 提取器**：现在的 `CodingFailureRuleExtractor` 只认 build/test 失败这一种硬编码规则。**2026-09-22 已从第二梯队提为 M7，排在 W8**（须早于 M5 基线评测，否则评测量的是临时替身）。

**第二梯队** —— 生命周期补全（supersede/archive 已实现，物理删除执行仍未做）、Consolidation Engine、MemoryRelation（spec 8.5 列了但表未建）、Feedback Service、评测扩容（现在只有 8 场景 1 条 golden）、限流。

### 已知缺口与它们的归属

外部评审 2026-09-22 提的五点已逐条核实属实，处置写在 `workplan-docs/总节奏表.md` 第五节，**权威口径是 README「已知缺口」那张表**。要点：CI 在 W4 接、删除幂等与防绕过测试进 M2、分页随 M4、LLM 提取器是 M7；**物理删除执行与限流明确暂不排期，不得声称已支持**。

`MemoryExtractor` 是 Protocol，本来就是为替换设计的 —— 换 LLM 提取器不需要动 worker。

## 密钥与产物

- `.local/` 存本地密钥（JWT 私钥、`ark.env` 里的 `ARK_API_KEY`），已被 `.gitignore` 忽略。**不要读其值、不要打印、不要提交。**
- 仓库里出现的 `local-development-only` / `local-app-only` 是**故意写死的本地开发占位口令**，不是泄露；生产账号应由密钥管理系统创建轮换。
- `.venv`（~150M）和 mypy/ruff/pytest 缓存是可重建产物，`uv sync --all-groups` 即可还原。
- **移动仓库目录后 `.venv` 必定失效** —— 里面的 shebang 和 `pyvenv.cfg` 写的是绝对路径，会报 `bad interpreter`。搬完先 `rm -rf .venv && uv sync --all-groups`，不要试图修补。

## 多机协作

本仓库会在 Mac、tx 服务器（Ubuntu 24.04）、Windows 之间流转，GitHub 是唯一事实源。**开工前 `git pull`，收工前 `git push`，不留未推送的提交过夜。** 同一时间只在一台机器上改。

## Docker 运行位置（用户明确要求）

**需要 Docker 时默认跑在 `tx` 服务器上**，不要在 Mac 或 Windows 上起容器。

确有必要在本地跑时，**必须先征得用户同意**，不要自行决定。

tx 上 `ubuntu` **已加入 `docker` 组**（2026-09-19），docker 命令不需要 `sudo`，Testcontainers 也可直接用。该机内存只有 7.5G，多个服务同时跑之前先看 `free -h`。

### 在 tx 上跑 Docker／测试前，必须先同步代码

本地改完直接去 tx 跑，而 tx 上还是旧代码 —— 结果是「测试通过」测的其实是旧版本，**这种假通过比失败更危险**。

用 `workplan-docs/scripts/run-on-tx.sh` 代替手工 ssh，它强制执行正确顺序：

```bash
bash workplan-docs/scripts/run-on-tx.sh agent-memory 'uv run pytest -q'
bash workplan-docs/scripts/run-on-tx.sh agent-memory 'docker compose up -d postgres'
```

它会：本地有未提交改动就拒绝 → push → tx pull → **校验两边哈希一致** → 才执行。哈希比对是最终判据，不是「命令有没有报错」。脚本还顺带剥掉了腾讯云登录横幅。

## 记录规范：新内容写到哪儿

**本仓库的正文只维护 `AGENTS.md` 一份**，`CLAUDE.md` 永远只是几行指路。两份都写正文必然漂移，**不要往 `CLAUDE.md` 里加任何内容**。

| 内容类型 | 去处 |
|---|---|
| 本仓库的指引、约定、边界、分工方式 | 本仓库 `AGENTS.md` |
| 环境、机器、工具链、跨平台的坑 | `workplan-docs/环境与踩坑记录.md` |
| 已经发生的进展、验证结果、失败与返工 | 本仓库 `docs/progress.md` |
| 关键设计取舍及其理由（面试要讲的） | 本仓库 `docs/design-decisions.md` |
| 排期、工时预算、里程碑 | `workplan-docs/总节奏表.md` |
| 岗位要求本身 | `workplan-docs/岗位要求原文.md`（唯一事实来源，不要在别处改写） |

写进「环境与踩坑记录」时，用 **［实测］**／**［预警］** 标注区分「已验证的事实」和「未触发的已知风险」，不要把推断写成结论。


## 2026-10-01 当前执行入口

M2/M3 与 W4 CI 的最新实际验收见 docs/progress.md（历史 103 tests 基线不可当本次结果）。`bash scripts/check.sh` 使用锁文件运行 pytest、ruff、mypy strict、foundation_runner；当前 shell 缺 docker 组时按环境记录使用 `sg docker -c 'bash scripts/check.sh'`。embedding 操作与夹具/真实 provider 边界见 docs/embedding-worker.md；生产迁移须另行核对部署数据库，当前本次只迁移 Testcontainers。

## 2026-10-07状态补充

M7真实LLM候选提炼与M5三组基线工程初验通过。真实模型、敏感检查边界及样本限制见docs/llm-extraction-and-baselines.md；四道门139测试通过。M6现已完成，见docs/context-builder.md；未新增常驻服务。


## 2026-10-08 评审后状态补充

历史说明保留为当时记录。当前能力和边界以 README 与 docs/review-hardening-2026-10-08.md 为准：提取临时故障先重试；显式命令幂等保留 7 天；0007 提供中文 bigram、纠正 reason、successor 关系；队列 admin 和共享 HTTP、查询缓存、OTLP/采样已实现。生产常驻服务与报警仍未部署。新生命周期权限必须单独授予，supersede 必须传 successor_id；版本历史必须 SQL 分页，不退回全量读取。


## 第二轮评审当前约束（2026-10-08）

当前细节见 docs/review-followup-2026-10-08.md：invalidated/superseded 只能继续 deleted，不准经 archive 绕过；中文 bigram OR 排序，不代表同义语义；ContentRejected 使用固定规则码，API 保留原错误码并附 reason_code，SDK 同步；异常向量第三次失败 dead，缓存先于 semaphore 检查。四道门 208 测试通过，旧报告是历史证据。


## 2026-10-19 用户新方案与阶段闸门

用户原件docs/agent-memory面试级完善方案.md已原样保存，优先按其任务卡推进；不自行改指标、切分、阈值。每阶段交付代码、报告、命令、环境指纹与遗留，负责人确认验收才进入下一阶段（方案§13.5）。本轮阶段0只修错/核实；B0标签是修复后源码，阶段2全指标报告仍待后续。开发记录docs/devlog/每任务一份，数字引用自动生成报告，署名如实保留Codex、具体模型版本未核实；不声称用户写代码或已经独立复核。

PG租约以数据库clock_timestamp为准，拿锁后再读时间，不用应用now或事务起点now判租约；内存适配器可注入时钟仅用于测试。HTTP支持conversation.message（user/assistant + bounded summary），仍是不可信事件，scope/JWT/RLS/提取验证保持。升级需要0008迁移；有对话历史时禁止有损降级，不为过测试删除生产数据。

整体HTTP正文默认1MiB，实际流量累计后才解析；超限413。版本offset上限10000，搜索offset2900等边界不取消。pip-audit使用冻结锁文件导出版本，原始前后扫描保留；不把一次0已知公告说成完全无漏洞。下游agent-ops-platform仍固定1e2730c，联调迁移源码须取其对应干净checkout，不自动升级其SDK pin。

## 2026-10-19 用户更新：持续推进

用户明确要求“持续进行直到完成，或者遇到需要我决定的再停下来问；每个阶段都要有交付报告”。此授权覆盖前述例行逐阶段确认暂停约定：技术闸门通过并交付报告后直接进入下一阶段，不再仅因未收到例行阶段验收回复而停工。仍不得改变指标/切分/阈值；真正需要负责人决策、人工标注/仲裁、缺少账号授权或不可达的数据才集中提问；等待期间继续独立工作。阶段0报告里的“例行等待验收”是当时状态，后续以本条用户新授权为准。

## 2026-10-19 后续用户修订：只交付阶段1

用户随后明确改为按阶段完成，本轮仅开发阶段1，交付后等待确认，不进入阶段2。共享TokenHub凭据已由/home/ubuntu/AGENTS.md授权，使用with-tencent按需注入，不再要求用户复制密钥；凭据存在与模型真实预检通过分别记录。负责人仲裁和盲审仍需真实人工完成，禁止助手代签。

## 2026-10-19 用户更新：耗尽后切换可用模型

用户授权免费试用耗尽时尝试其他可用模型，不因单个模型402停止；不授权充值或开启后付费。替代模型先验证可访问性与评测预检，保持双标注厂商独立、裁判角色独立，并记录具体模型/提示词/请求配置。不同模型的部分标签保留为独立实验，不静默拼成同一冻结模型结果。阶段范围仍仅阶段1。Ark旧版Pro访问失败与账户额度分开核查，不由404推断全部Ark模型不可用。

## 2026-10-19 用户确认Ark新版

用户明确“改用新版doubao-seed-2-1-pro-260915”。阶段1及后续获授权评测的抽取/对话、答题使用该ID，角色配置docs/evals/model-roles-v2.json。通过with-ark与scripts/with-phase1-runtime.py只注入目标子进程的新版抽取配置，不改共享密钥、无关服务、历史报告、B0标签或原始用户方案。完整预检与任务校准仍必须分别完成。向量配置不随对话模型改变。

## 2026-10-19 采样策略纠错（优先于此前模型候选记录）

原方案§7明确排除采样固定的Kimi，现官方Kimi-K3指南仍写固定温度且不可关思考。先前仅凭100格式/5次一致就把Kimi视为合格是执行错误，已停止；该模型的历史部分标签只留作探索，不进入正式数据/裁判/盲审。诊断可保留，但预检必须同时满足格式、一致性及模型参数资格；API接受字段不等于字段生效。当前角色以model-roles-v3.json为准，v2保留历史但不再使用其Kimi角色。公开中文第二标注候选改为文档支持温度0、关闭思考的deepseek-v4-pro-0813，先完整预检；合成集仍DeepSeek4.1+MiniMax2.7，裁判候选GLM；公开中文GLM+新DeepSeek时裁判候选MiniMax，厂商逐数据集独立。禁止为省额度放松这些要求。

## 2026-10-19 负责人确认盲审阈值

用户已明确回复“盲审95%”：负责人10%盲审一致率须≥0.95，模型间κ≥0.7不变。冻结配置docs/evals/human-review-policy-v1.json。阈值批准不等于批准任何实际标签或阶段验收，不代签；历史报告中的“阈值待确认”是当时状态，后续按本条执行。

## 2026-10-20 本轮仅真实中文补量

本轮只处理阶段1真实中文缺口，具体约束见docs/evals/chinese-expansion-policy-v1.json。标注模型按最新用户指令固定deepseek-v4-pro-0813、minimax-m2.7；此条优先于此前“额度耗尽自动换模型”的泛化授权，更换前必须说明理由并等待负责人确认。语料原生参照不以模型保留票筛掉，仍须真实人工抽检；PerLTQA为作者模型生成并修订的基准，不计真实中文规模。ECD大小/CRC要核对，源语料和审核原文仅本地，对外只有清单哈希、方法指标。冻结来源会话切分继承，不改指标/阈值，不代人工审核，不进入阶段2。实际响应违背关闭思考设置时拒绝接收，不能仅凭参数被接受或旧预检通过认定当前合格。

## 2026-10-20 后续授权：模型故障自动替换

用户随后明确“换模型继续，以后遇到类似的问题都这样做”。覆盖上一条逐次更换需确认的限制：额度耗尽、接口不可用或采样控制不生效时，自动挑选其他独立厂商模型；先核对文档并预检，合格后冻结新组合、对当前固定数据完整双标，保留旧实验与用量，不跨模型拼标签。不降低指标/阈值，不改切分/标注指南，不充值或开后付费，不代替负责人审核。新模型及切换原因写入版本化配置和交接报告；常规模型替换不再重复请求许可。仍仅阶段1，真正缺少凭据、所有合格可用模型耗尽或需修改既定标准时才问负责人。

## 阶段1第三轮用户修订（优先于此前自动替换标注模型授权）

本轮只处理 agent-memory，不进入阶段2。标注组合冻结 deepseek-v4-pro、mimo-v2.6-flash；故障更换须先说明原因、等负责人确认，并整批重标。裁判允许预检合格后按实际剩余额度自动切换，但一张对比表必须使用同一裁判；切换时整表重判，每条记录模型与返回版本，额度未知不虚构排序。

ECD 不再作为双标抽取金标、无 κ≥0.7 闸门；共同舍弃仅作人工未核验负样本；固定种子另取100–150段供负责人直接标记应记内容。原文仅服务器本地和负责人私有包，不能发群或进Git；不再生成616条仲裁包。当前只要求负责人填 DuLeMon native-reference 的230抽检，其余旧审核暂缓，不催办；ECD小样表预备但不扩大本轮必填范围。人工回填按冻结原生参照算一致率，低于95%仅采用人工确认子集并重算规模。合成集与冻结标注组合不一致时仅提重标方案，不自行重标。详细执行配置 docs/evals/phase1-round3-policy-v1.json。原方案仓库副本是否包含本轮修订须核对，不把旧副本称最新版。

## 阶段1第三轮收尾授权（2026-10-21）

负责人已批准合成时间线用 deepseek-v4-pro 与 mimo-v2.6-flash 整批重标，覆盖此前仅提方案的限制。输入/切分/指标不变；新批次与旧标签完全隔离，遇到额度故障保留未完成状态，不自行换冻结模型。裁判余额排序/冻结等待控制台截图，不为探余额额外调用、不充值或开启后付费。允许跨云运行入口的模拟402整表重判演示；这不是阶段2验收。

随后负责人对本轮合成重标的402明确授权“换模型继续完成”。这只放开本轮合成时间线替代组合，公开中文旧批次不重写；新组合须独立厂商、采样控制与完整预检合格，并整批重标。当前拟定Ark DeepSeek正式版与腾讯HY4，状态/资格以本轮报告为准。涉及新合成批次时腾讯已是标注厂商，正式裁判池一并排除；模拟路由演示不代表正式裁判资格。

## 2026-10-21 最新方案与第三轮后续

最新版用户原件在 docs/plans/2026-10-21-agent-memory-interview-plan.md，完整保留原作者；旧 docs/agent-memory面试级完善方案.md 为历史版本，差异由报告脚本导出。当前执行配置 phase1-round3-policy-v2.json 优先于 v1 的余额截图/排序、全厂商并集排除规则。

裁判按每张表的答题厂商和实际标注厂商独立排除；预检通过且实际调用成功后按明确顺序冻结主备，不查余额。每表至少两个合格备选；不足时如实列缺口，不把同厂商换渠道误称角色独立。主备均须真实人工校准方可发布正式判分，切换整表重判。公开中文标注不变；合成已授权替代组合独立保留。

合成时间线当前只标“流程验证，不作质量证据”，不得以一致率或 κ 证明真实标注质量。中文查询独立统计真人对话衍生、作者模型生成基准、程序合成；不能混入真实中文金标规模。所有旧切分、指标与验收阈值不变。

负责人本轮只填 DuLeMon 原230抽检的实际核对行，其余人工栏留空；只对非空有效人工行按冻结参照计一致率，低于95%仅输出人工确认子集。程序不得自动读取旧 Agent 标签作为人工结果。ECD120审核表逐字节保持，不催办其他暂缓包。阶段1仍未验收，不进入阶段2。

## 2026-10-21 负责人真实回填与独立困难集

真实回填来源 dulemon230-for-agent.csv，已核对行按旧Agent标签选择，非随机；人工与冻结原生参照比较，不用旧Agent结果充人工。空白保持空白，上下界按全表分母计算；低于门槛只导出独立人工确认子集，不覆盖原生标签/切分。补足路径与查询替换先给可审阅方案，待负责人确认。

synthetic-hard-v1 是独立程序构造集合，构造真值不是人工标签，小样对照调用不代表全量双标完成。原时间线与困难集都只作流程验证；ECD表不动。当前裁判策略v3撤下预下线GLM-5V；旧预检通过仅留历史，禁止用旧证据绕过当前撤下名单。主备缺口及人工校准仍须如实报告。阶段1未验收，不进入阶段2。


## 2026-10-21 获批补量与查询启用（后续最新）

最新原件另存 docs/plans/2026-10-21-agent-memory-interview-plan-v2.md，旧版保留。策略v4：真实中文经抽检通过的记忆点下限700、目标1500；独立随机盲抽72，错误最多3。排除以前按旧Agent标签挑选且已人工核对的项；不能用模型补人工。审核八列与原表一致，不透明item_id、source原JSON、人工栏空白；负责人已明确格式并授权真实表直接私发。抽检通过后才增量补量；冻结标注组合失败仍须请求更换授权。

新版查询启用chinese-queries-v2-hard，旧版不可覆盖，新旧不可同集比较。时间推理/知识更新/多会话单列流程验证，不进质量汇总；困难集人工抽检暂缓。裁判至少一个严格合格备选，公开表数量满足不代表校准通过；合成表不足仍报告，不放宽预检或恢复预下线模型。ECD保持、不催办；阶段1未验收。


## 2026-10-21 共同保留池真实回填后的约束

新人工回填来源dulemon72-final.csv，原池独立盲审未过最多错误三条的门槛；不得以人工keep项推定整池通过。只把原ID去重后的具体人工确认项并入human-confirmed-current.json。后处理原型不可用，不能拿高已知错误召回掩盖误伤。原数据已用于规则开发，后续验收须新独立样本；不足不得复用或抽重。

逐字核验规范：所有具体细节与主体关系须有用户本人原话依据，无依据完整候选降级，不从助手自述、问句、否定或别人的事补用户事实。原型输出不是人工标签，不覆盖负责人确认结果。当前过滤方案未批准，增量标注禁止；如需改写冻结候选或改变复核流程，先给新版本与整批范围供负责人确认。阶段1未验收，ECD/困难集暂缓审核不变。

## 负责人批准标注规程v3（最新）

仅修改公开中文冻结模型对的提示词，使用docs/evals/labeling-guide-v3.md及独立证据响应。程序只精确验证source_id、用户角色、原文子串，不能把词法拼接或主观规则当语义证明。229真实人工项固定按会话开发/最终隔离；最终集不反复调提示词。离线未完成或未达门槛禁止整批重标，整批完整后再抽未审72；补量继续等新盲审通过。失败保留台账，不自动换冻结模型。所有报告、审核表、附件发送当前群，不再私发（负责人最新交付偏好）。阶段1仍未验收。

## v3替代组合已获批准（后续最新）

负责人明确“换模型继续”后，DuLeMon v3新批次单独冻结Ark deepseek-v4-pro-ga-260813与TokenHub hy4-preview；见docs/evals/annotation-v3-replacement-freeze.json。原公开中文标签仍留历史，禁止与新批混用。开发/最终切分原样继承，不能因换模型重抽更容易的题。离线通过后整批重标，不只接旧标签尾部。新表裁判排除DeepSeek、腾讯及答题厂商字节，不沿用HY4作裁判。补量仍等新盲审通过，阶段1未验收。

## 负责人新决定：产量指标与701池盲审（最新）

本轮policy为docs/evals/pool-refresh-policy-v1.json：正确项保留率仅报告，不是通过门；既有8/9拦截已获认可，不做新离线验证。只用开发输出与虚构例修订格式，不复用最终集。701池完整新标后独立抽未审且未用于开发/最终的72条，最多3错，未过盲审禁止增量。旧门槛与失败报告留历史。正式finalizer须用真实人工标签投影，黑名单占位值不充人工。Ark上限触发即停止，不自动改限额/计费或换模型；恢复须同提示词同模型。阶段1未验收。

## 模型额度不足自动换型（负责人最新授权）

负责人明确“模型额度不足就换模型，ark不足就用腾讯云的模型”，因此额度/账户用量上限阻塞后不再等待换型确认。先技术预检，额度不足在有界合格候选中自动换；受影响模型侧必须全池新标，旧部分标签留历史，不接尾混用。另一侧完全相同输入/提示词/模型的完整标签可整份校验复用，不重复付费。入口scripts/continue-pool-with-quota-fallback.py；当前策略docs/evals/tokenhub-pool-fallback-policy-v1.json。省略供应商不支持的API JSON模式不等于放宽程序JSON/证据校验；校验器不变。仍禁止修改服务用量上限/计费。新盲审未过不补量，阶段1未验收，所有交付发本群。

## 2026-10-22 长期记忆与时效性筛选（当前）

最新原件 docs/plans/2026-10-22-agent-memory-interview-plan-v3.md（SHA256由交接脚本核对）；旧版不覆盖。阶段1只做长期记忆，短期有效期机制是以后可选项，不提前实现。真实新盲审按69 keep/3 discard核算，以收到的CSV与冻结模板为准，早先“72全部keep”消息已被负责人更正。新增69项与既有人工项按原ID去重；不能把整池称逐条人工确认。

采纳前对原265条及人工正例对照仅新增长期/临时判断，任一方临时即提出剔除，不新增候选。筛选无自行设置的通过线；结果交负责人决定后才采用旧池筛选结果。新增量已获授权采用同样时效性标准，所有引用校验维持原样；新增池须再次独立72盲审通过才计规模。额度不足允许技术合格备选替换，受影响一侧整批重标，不混用部分标签；报告实际标注厂商对裁判排除的影响。只在本群交付，阶段1仍未验收，ECD表不动。

## 时效性增量固定批与格式拒绝（2026-10-22后续）

增量以固定100段为独立批，首批完成前已冻结此执行范围。额度换型重标当前批受影响模型侧全部输入；已完成批保留完整来源，不拼接当前半批，报告各批实际厂商并按对比表实际数据排除裁判。原始响应结构/引用不合格的条目程序拒绝为uncertain，不修复字段、不降低原精确引用标准；程序uncertain不得当模型语义标签计算一致率。缓存只重放真实响应并重验，不把历史usage当新调用。

ECD新人工回填已获授权接入，仅方法哈希指标公开；来源必须称AI草稿加人工确认，不能称独立人工。旧ECD120模板仍保留不改。旧265池时效性采纳继续等负责人决定；新补量独立盲审未通过前不能计入可靠规模。当前阶段1仍未验收。

## 单条请求恢复（2026-10-22最新）

多候选腾讯Turbo实际根结构失败不等于额度耗尽。虚构全格式预检与真实分组控制均独立保存；当前V5入口/scripts客户端v3对该型号每请求一条，原提示词、候选、严格结构/引用校验不改，不修补原响应。排查真实ID见.local/phase1/round3/temporal-v1/transport-probe-excluded-ids.json，须排除后续盲审及可采纳池。旧失败快照留历史，不把它冒称当前运行状态；所有状态以increment-current.json及实际进程/台账为准。新增目标未完成时阶段性72包只本地准备，不发负责人催审；完整补量后再交新增独立盲审。所有交付仍只本群，ECD原文不公开，阶段1未验收。

## 当前运行已因真实402关闭（2026-10-22最后状态）

V5单条调用修复了格式问题，但随后当前腾讯侧也返回402；运行已结束，increment-current.json指向当前冻结尝试，报告仍phase1_accepted=false。未完成当前批不入金标，已完成候选未盲审不采纳；目标未完成的阶段性72表仅本地准备，不发催审。不是全目录余额结论，剩余额度没有查询。后续恢复应新建独立尝试，保留失败台账，复用同模型同输入真实响应；若换型则当前受影响侧整批重标。不得直接重跑已标失败ledger、删除失败记录、放宽结构/引用标准或开通计费。当前真实状态与细计数见closeout-status.json及交接报告，所有交付仍只本群。

## 负责人旧池采纳与新增账户（2026-10-22最新）

按docs/evals/phase1-new-accounts-policy-v1.json执行。旧未审池仅扣人工已知错误，时效性筛选保留参考不用于剔除；与逐条人工正例按原ID去重后作为补量基数。新增池仍执行临时不得keep，补量完成且独立盲审通过前不计可靠规模。新账户预检须真实完成，旧账户成功不代替新预检；目录可读不代表模型可调用。未完成批index4两侧整体作废，新账户客户端v4只允许本轮范围真实响应缓存，禁止重放旧单侧。后续额度换型仍整侧重标，完整历史批保留来源。新取样与盲审种子独立，排除全部历史审核、开发、最终及技术调试项；ECD保持原样。所有交付发当前群，阶段1仍未验收。


## 阶段1已验收、阶段2 B0获准（2026-10-23最新）

负责人已明确验收阶段1并启动阶段2，见docs/evals/phase1-acceptance-current.json与b0-policy-v1.json。B0标签不可覆盖，只加载其冻结业务源码；框架可新增，不优化系统。所有指标仅开发集，测试集保留最终一次性运行。校准300表人工栏空白、隐藏裁判结果、仅服务器私有，交负责人后暂停；未校准分数不正式发布。运行时抽取/向量化额度不足暂停，不自动换型；其他角色切换须整表或整组，独立厂商要求不变。压测待独立跨地域Linux固定IP机器，说明见docs/baselines/b0/load-generator-preparation.md。三类构造题只作流程验证，不混质量总分；不进入阶段3。


## 负责人同系列续跑授权（北京时间2026-10-24，覆盖此前换型号整组重跑）

消息om_x100b628d31ba14a0df2cc7d1869eac1明确允许同系列模型额度切换后继续。当前policy-v5/sample-v8，保留并验证完成的会话组合与逐题答题判分检查点，实际型号/Key代号/原始调用/父哈希留痕；版本混用不称精确单型号实验。不同系列仍整组重跑；向量化不同模型/提供方/协议不混用旧向量空间。预检、厂商独立、人工校准、仅开发集与阶段2范围不变。300人工表仍导出后暂停，不代判、不进阶段3。


### 2026-10-27 负责人校准补充口径

本次任务以负责人消息om_x100b6133e7ac4cacc069e724a36afa5为准：采用κ≥0.7或准确率≥90%，替代先前κ单闸门。人工原CSV和理由不可修改，回填只服务器私有使用。`scripts/calibrate-b0-owner.py`为单一校准入口，先验证300个ID/冻结字段，再关联原GLM和同批已有MiniMax交叉判分；备选与交叉参照同模型，不称独立。`agent-memory-b0-calibration-20261027.service`正在同批固定100条×3×两模型新增600次判分；断点私有`calibration-owner-20261027/repeats-private.json`，原始调用留痕。整批结束自动更新聚合B0报告、本地交接并发送聚合报告至本群，人工逐行数据不外发。飞书Wiki仍暂缓，不进入阶段3。公式方向/无效输出/稳定性分母三项回归通过，未改业务或冻结提示词，无提交推送。


### 2026-10-27T18:36:29.156896+08:00 聚合报告交付暂缓

负责人消息om_x100b6133a655c8a8c0ae8068a9f07da明确要求未完成则完成后再发。本轮1560答题判分及300人工校准、同批100×3×两裁判均已完成，但全功能指标覆盖与独立跨公网PF尚未齐；不把当前带缺项报告作为最终完成版发出。本次没有发送新的聚合文件。交付状态见docs/evals/b0-current.json的aggregate_delivery_request；后续收尾须先核查完整性与本条交付约束，不因已有delivery.md就自动外发未完成版。原始标签/理由不动，飞书Wiki仍暂缓，不进阶段3。
