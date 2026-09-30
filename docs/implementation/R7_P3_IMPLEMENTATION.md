# P3 实施说明（R7 Findings F5 / F6 / F8 + Session 统计 / OPEN 提前诊断）

- 日期：2026-09-29
- 基线：P2 正式发布 commit `30dd540ee0f530908992229087722d4701612954`
- 工作树：`F:\NewResearch\scaffold-r7-p3-implementation`（分支 `r7-p3-implementation`，从 P2 commit 新建独立 worktree）
- 本轮只实施 P3 授权范围；未修改 main、P1/P2 工作树、主仓库工作现场；未 Commit/Push/合并（等待独立审计）。
- 正式授权原则保持：只有 Git Commit 与 Git Push 需要人工授权，其余正常开发操作自主执行。

---

## 1. 实际修改文件清单

源码（6 个文件，+577 / -24）：

- `src/scaffold_p7/engine.py`：F5。`COMPLETE_ENVELOPE_KEYS` 增量加入 `stage_decisions`；`complete_run_opts` 预校验批量结构（非 list/空 list/非对象项整体拒绝）并映射 `stage_completion_decisions`；批量隐含 `request_stage_complete`；`run` → `prepare_lifecycle` 透传；`_requests_satisfied_completion` 覆盖批量（published report 的 TEST_PASS 门禁同样约束批量路径，不绕过）。
- `src/scaffold_p7/lifecycle.py`：F5 主体 + F7。`prepare_lifecycle` 新增 `stage_completion_decisions` 参数与原子校验（`_batch_stage_decisions_error`：空批、重复 stage_id、与单数 decision 绑定冲突、逐项 `_stage_completion_authority_error`）；分发复用 `apply_stage_decision`/`maybe_complete_stage`/`revalidate_complete_stage`；新增 `open_session_drift_warning` + `_latest_sealed_session_for_task` + `_previously_attributed_paths`（F7，只读诊断）。
- `src/scaffold_p5/engine.py`：F6。`_resume` 不再调用 `emit_working/emit_idle`（不再写 progress.json），改用 `_resume_heartbeat`（仅 stderr 终端心跳）。
- `src/scaffold_p5/progress.py`：抽出 `_write_progress_timestamp()` 共享时间戳（行为不变），供 resume 心跳复用。全局 Progress 机制本身未删改。
- `src/scaffold_p5/resume.py`：Session 统计。新增 `session_status_counts()`，写入 resume 公开结果 `authority.work.session_status_counts`。
- `src/scaffold_p5/shell_boundary.py`：F8。新增 `_git_discard_shaped`（restore）与 `_checkout_discard_shaped`（checkout -- / tree-ish -- path）判定与 `GIT_DISCARD_ALTERNATIVE` 阻断理由；`reset --hard` 仍由既有 `GIT_DESTRUCTIVE` 全量阻断。

文档（1 个文件）：

- `docs/PUBLIC_LIFECYCLE_REFERENCE.md`：§2 信封字段表新增 `stage_decisions` 行（原子性/兼容性合同）；新增 §4.1 Session 状态统计、§4.2 Resume 只读化、§4.3 Session OPEN 提前漂移诊断、§8.1 丢弃型 Git 操作自动防护。

测试（1 个新文件 + 1 个既有文件小改）：

- `tests/test_r7_p3_implementation.py`：36 项新用例（全部通过）。
- `tests/test_command_test_autonomy_lightweight.py`：门禁提升同步——`git checkout HEAD -- src/app.py`、`git restore src/app.py` 从 allow 改为 discard 阻断（原 allow 断言与 F8 防护直接矛盾；保护治理路径断言全部不变）。

未触碰：`skills/` 四个 Skill 包（package_digest 与 P2 基线逐位一致，由 `git status` 佐证零改动）、Task Book、Gen1→Gen2 Migration、P1 Adoption 合同、P2 install-managed 分类、P2 Evidence Staleness 诊断、Session/Task/Ownership/Evidence 门禁。

## 2. F5 批量信封合同

- 公开字段：`stage_decisions: [decision...]`，每个 decision 是结构同 §2.1 的单个 Stage Completion Decision，必须精确绑定一个真实存在且唯一的 Stage。
- 单数 `stage_decision` 永久兼容：字段保留、语义不变、可与批量并存，但两者绑定同一 Stage 时整体拒绝（冲突防护）。
- 生命周期组合：批量与 `task_decision`、`complete_stage`、`ready` 组合走既有 `prepare_lifecycle` + `persist_ready_if_legal` + CAS 发布链路，遵守现有生命周期。
- 门禁不绕过：批量 decision 中的 SATISFIED 请求同样触发 `_requests_satisfied_completion` → 消费 published report 时强制 TEST_PASS；basis/Evidence/required tests 校验逐项复用现有实现；Candidate 变化后 stale decision 无法支撑 COMPLETE/READY。

## 3. 批量操作原子性证明

`_batch_stage_decisions_error` 在**任何 Task 变更发生之前**对全部 decision 逐项校验；任一非法（绑定不存在/歧义 Stage、重复 stage_id、与单数 decision 冲突、结构非法）立即返回 blockers，`prepare_lifecycle` 以未变更的 `deepcopy(task)` 返回。校验失败时：无 decision 落盘、无 Stage 状态变化、无 Task 发布（`publish_task` 仅在 `lifecycle_progressed` 且全部校验通过后调用）、无 Session 副作用、无 Evidence 绑定副作用。`test_F5_07`（非法 Stage 整体拒绝 + 逐字节断言 stage-1 未变）、`test_F5_10`（engine.complete 端到端 BLOCKED + Task Book 无部分发布）证明。

## 4. F6 Resume 只读验证

- `_resume` 移除 `emit_working/emit_idle` 调用；`resume_project` 本身为纯观察（无写入路径，源码核对确认）。正常 resume 全程不写 `progress.json` 或其他持久文件（`test_F6_01`：resume 后 progress.json 不存在；`test_F6_02`：两次 resume 持久树逐字节一致，幂等）。
- 终端心跳保留：`_resume_heartbeat` 输出与 WORKING 心跳同格式的 stderr 文本（`scaffold: WORKING understand.resume start/done at=...`）。
- 全局 Progress 机制未删除：其他长时操作（develop session/complete/seal、Test）行为不变（`test_F6_04`）。
- 中断 Session 恢复观测：ORPHANED Session 仍出现在 resume `work.sessions`（`test_F6_05`）。
- 历史佐证：P2 基线失败的 `test_dive_pilot_correction05.py::test_R05_resume_mutates_nothing` 与 `test_R13`（断言 resume 不改文件）在 P3 上转绿（21 passed），独立证明 F6 达成目标。

## 5. Session 状态统计

`session_status_counts()` 基于 `inspect_sessions()` 的实时权威枚举，不新增第二套 Session 权威记录、不读聊天/缓存：`counts` 提供 OPEN/SEALED/ABORTED/UNKNOWN 四类计数；`anomalous` 逐条保留 ORPHANED/MALFORMED/UNREADABLE/身份非法 Session 的 record_id+status+reconstruction，统计失败不静默删除异常 Session；`source` 标注 `inspect_sessions live enumeration`（`test_S01`/`test_S02`）。

## 6. Session OPEN 提前漂移诊断（F7）

`develop session` 成功路径 extras 新增只读 `drift_warning`（status: NONE/DIVERGED/UNKNOWN），三项检查：

1. Candidate 绑定：OPEN Session 记录的 digest 与当前 Candidate 一致性；
2. 未归属漂移：排除 Task scope 内合法授权变化、Scaffold 治理面（`.scaffold/**`/AGENTS.md——归属由 P2-F3 reconcile 权威判定）、既有 drift 权威已归属路径（`unexplained_path_map`）后，报告 scope 外未跟踪漂移；
3. 最近 SEALED 证据关系：最近 SEALED Session 的 Candidate 与当前不一致时提示（权威 stale 判定仍由 P2 Evidence 门禁在消费时做出，本诊断不重复不替代）。

边界：不修改/不删除历史 Evidence（`test_F7_05` 逐字节断言）；Session 无 candidate digest 或 SCM 观测不可用时报 UNKNOWN，不伪造 Candidate 身份（`test_F7_04`）；正常授权开发不误报（`test_F7_01`/`test_F7_02`）；真实未归属变化触发告警（`test_F7_03`）。

## 7. 危险 Git 操作防护（F8）

- 审核结论：现有 `GIT_PUBLICATION`（commit/push 人工授权）与 `GIT_DESTRUCTIVE`（rebase/reset/clean/filter-branch/am/force-push 硬边界）不变；正式授权合同无需修改，**未发现合同冲突**。
- 新增自动风险判断（无人工审批）：`git checkout -- <paths>` / `git checkout <tree-ish> -- <paths>` 与 `git restore [<paths>]`（worktree restore）判定为丢弃型，自动阻断并说明风险与非破坏性替代路径（先记录当前内容或完成授权 Commit 再重新应用丢弃）；`git reset --hard` 维持既有 destructive 阻断。
- 不误伤：分支切换（`checkout <branch>`/`-b`/`-B`/`-t`/`--orphan`）、检查类命令（status/log/diff/show/blame）、`restore --staged`（仅动 index 不丢工作树内容）保持自主（`test_F8_04`/`test_F8_06`）。
- 不约束 Agent 会话之外用户直接执行的 Git 命令（该行为不经此边界）。
- 既有测试同步：`test_command_test_autonomy_lightweight.py` 中 `git checkout HEAD -- src/app.py` / `git restore src/app.py` 两条 allow 断言更新为 discard 阻断断言（原断言与 F8 防护矛盾；P2 报告审计口径"未修改既有测试"的约束仅针对已通过审计的 P2 交付，本条为 P3 授权范围内门禁提升所必需，保护治理路径断言与 publication/destructive 断言全部原样保留）。

## 8. 测试结果

新增回归：`python -m pytest tests/test_r7_p3_implementation.py -q` → **36 passed**。

覆盖清单（对应任务要求）：批量三个 Stage Decision（F5_06/F5_11）；非法 Stage 整体拒绝（F5_07/F5_10）；重复 Stage ID（F5_08）；单数信封兼容（F5_01/F5_05）；批量与 READY 组合（F5_11）；Candidate 变化后批量拒绝（F5_12）；resume 前后文件稳定（F6_01/F6_02）；重复 resume（F6_02）；Session 状态统计（S01/S02）；正常授权开发不误报（F7_01/F7_02）；真实未归属变化告警（F7_03）；危险 Git 恢复操作识别（F8_01/F8_02/F8_03/F8_05）；正常 Git 检查不受影响（F8_04/F8_06）；安装及更新兼容性（下述定向回归）；no-SCM 适用路径（N01）。

定向回归（均通过）：

- `test_r7_p1_implementation.py test_r7_p2_implementation.py test_r4_maj008_unexplained_drift.py test_command_test_autonomy_lightweight.py`：121 passed, 1 skipped
- `test_develop_autonomy_lightweight.py test_p7_develop.py test_p7_rev1.py test_p7_rev2.py test_p7_closure.py`：103 passed
- `test_consumer_installation.py test_consumer_self_update.py test_compatibility_lock_update_public.py test_pc_r4_client_neutrality.py`：127 passed + 3 subtests
- `test_public_lifecycle_completion_surface.py test_first_use_enforcement.py test_fa2_batch5_develop_lifecycle.py`：109 passed + 4 subtests
- `test_dive_pilot_correction05.py`：21 passed（含 R05/R13 由 F6 修复转绿）

## 9. 与 P2 基线的全量回归对比

全量口径：`python -m pytest tests/ -q --tb=no`（相同环境、相同测试选择条件；基线在 `30dd540` 临时 detached worktree 实测后已清理）。

两组统计事实并存：

- 实施阶段某一轮全量运行：P3 = **1995 passed / 16 failed / 16 errors / 2 skipped**（+15 subtests passed），P2 基线 = 1956 passed / 19 failed / 16 errors / 2 skipped。
- 独立审计同环境重新运行：P2 baseline = **1956 passed / 19 failed / 16 errors / 2 skipped**，P3 = **1994 passed / 17 failed / 16 errors / 2 skipped**。

精确解释两组结果的差异：

- `R05` 与 `R13`（`test_dive_pilot_correction05.py` 中断言 resume 不修改任何文件的用例）因 F6 修复在 P2 与 P3 之间稳定转绿，这是两次运行中一致的稳定收益。
- `P9_R10` 是既有 Windows 并发 CAS flaky 用例，与 P3 变更无因果：实施阶段运行中它恰好通过，独立审计运行中 P2 与 P3 均失败。不得将 `P9_R10` 的单次通过描述为 P3 修复，也不得把该单次通过计入稳定收益。
- 逐用例对比确认：审计轮 P3 的 17 failed = 实施轮 16 failed 全集 + `P9_R10`（flaky 抖动），其中 16 个为 P2/P3 共有历史失败（B9D06、RA_MIN02、PF2_03、C003×10、IMP03/IMP07、FND5_E02），16 errors 完全一致（历史 `test_engine` 命名误收集）。**P3 新增失败 = 0**；独立审计失败集合对比确认没有 P3 新增回归。
- 未为通过测试降低任何门禁；唯一既有测试断言修改是 F8 门禁提升所致（见 §7）。

## 10. 尚未解决的问题

- R7 审计矩阵 09/10（合同强度修订）不在 P3 范围，未实施。
- MINOR（独立审计记录）：`drift_warning` 当前对 scope 外 tracked-M 手工修改的提前诊断灵敏度有限。该项为 advisory-only 诊断限制，不影响生命周期 authority，本轮不修改源码。
- `drift_warning` 的 `unattributed_drift` 检查当前仅覆盖 untracked/A 类 entry；已跟踪文件的 modify（M 类）与既有权威归属的重叠判断依赖 `unexplained_path_map`（reconcile 前可能为空），M 类归因增强可留待后续。
- 基线既有失败（C003×10、IMP03/IMP07、FND5_E02、B9D06、RA_MIN02、PF2_03）与 `test_engine` 误收集 ERROR 属历史域，本轮未修复。
- C003 等历史失败域与 F8 行为变化无因果（基线 worktree 复测失败集合与本轮逐项一致）。

## 11. 候选代码快照

- 分支：`r7-p3-implementation`（未 commit，工作树即快照；本轮禁止 Commit/Push）
- 独立审计结论：`R7_P3_INDEPENDENT_AUDIT_PASS`——P3_F5 / P3_F6 / P3_SESSION_STATUS / P3_F7 / P3_F8 / P3_COMPATIBILITY / P3_REGRESSION / P3_INDEPENDENT_AUDIT 全部 PASS；BLOCKING = 0，MAJOR = 0，MINOR = 2（见 §10）；SAFE_TO_COMMIT = YES。
- 修改：`docs/PUBLIC_LIFECYCLE_REFERENCE.md`、`src/scaffold_p5/engine.py`、`src/scaffold_p5/progress.py`、`src/scaffold_p5/resume.py`、`src/scaffold_p5/shell_boundary.py`、`src/scaffold_p7/engine.py`、`src/scaffold_p7/lifecycle.py`、`tests/test_command_test_autonomy_lightweight.py`
- 新增：`tests/test_r7_p3_implementation.py`
- 与 P2 发布 commit 差异：8 文件 +610/-24 + 1 个新测试文件；`skills/` 零改动。

## 12. 独立审计检查点

1. `lifecycle.py` `_batch_stage_decisions_error`：确认校验发生在任何 mutation 之前；重复 stage_id、单数冲突、不存在 Stage 三类拒绝各自独立成立；`_stage_spec_for_stage` 批量优先、未绑定 Stage 返回 None（不误用单数 spec）。
2. `engine.py` `_requests_satisfied_completion`：确认批量 SATISFIED 同样触发 published report TEST_PASS 硬门禁（不得绕过）。
3. `scaffold_p5/engine.py` `_resume` / `progress.py`：确认 resume 路径无任何持久写入；`emit_working/emit_idle` 其他调用方行为不变。
4. `resume.py` `session_status_counts`：确认统计仅来自 `inspect_sessions` 返回值；异常 Session 进 `anomalous` 不丢弃。
5. `lifecycle.py` `open_session_drift_warning`：确认为只读诊断（无 write 调用）；治理面排除与既有归属排除逻辑；UNKNOWN 优先级正确。
6. `shell_boundary.py`：确认 Commit/Push/destructive 边界语义未变；新增阻断仅限 discard 形态；`checkout <branch>`/`-b` 与 `restore --staged` 不被误拦。
7. 回归对比：建议审计者重跑 `test_r7_p3_implementation.py`、`test_command_test_autonomy_lightweight.py`、`test_dive_pilot_correction05.py` 与全量对比口径。
8. `git status` 佐证：`skills/` 与既有已发布工作树零改动；本轮未执行任何 Commit/Push。

R7_P3_IMPLEMENTATION_COMPLETE
