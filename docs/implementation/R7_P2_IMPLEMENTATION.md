# P2 实施说明（R7 Findings F3 / F4 / F7）

- 日期：2026-09-29
- 基线：P1 发布 commit `e2dcbfd32036017cd62c015e5f951faa35df349f`
- 工作树：`F:\NewResearch\scaffold-r7-p2-implementation`（分支 `r7-p2-implementation`，从 P1 commit 新建）
- 本轮只实施 P2 授权范围（F3/F4/F7）；未重新实施 P1，未扩展至 P3，未 Commit/Push（等待独立审计）。

---

## 1. 实际修改范围

源码（3 个文件，213 行新增 / 3 行删除）：

- `src/scaffold_p7/unexplained.py`：F3 主体。新增 `CLASS_INSTALL_MANAGED = "install-managed"` 分类、`_install_managed_verified()` 可信安装验证函数，`reconcile_unexplained_drift()` 三处分类分支，`unexplained_matches_current()` 覆盖新分类。
- `src/scaffold_p6/published.py`：F7。`consume_published_report()` stale 拒绝点注入 `stale_evidence` 结构化诊断，`published_report_skill_result()` 透传到 extras。
- `src/scaffold_p7/lifecycle.py`：F7。`_judge_requirement()` stale 拒绝理由附带 `current_candidate_digest` / `evidence_candidate_digest` / `evidence_locator` / `remediation`；新增 `observe_candidate_digest()` 辅助函数。

文档（1 个文件）：

- `docs/PUBLIC_LIFECYCLE_REFERENCE.md`：F4。§2.2 扩充零上下文 Agent 结构化测试绑定五问指引；新增 §2.2.1 Stale Evidence 诊断字段合同。

测试（1 个新文件）：

- `tests/test_r7_p2_implementation.py`：16 项用例（15 passed + 1 skipped）。

未触碰：`consumer_install.py`、`delta.py`、Session/Task/Evidence 门禁、Gen1→Gen2 Migration、skills.lock、四个 Skill 包（package_digest 逐位不变）。

## 2. F3 根因与修复机制

根因：Scaffold 安装的 MANAGED 文件（`.scaffold/install/**`、`.cursor/skills/scaffold-*` 等）不在 Git accepted anchor 中；安装先于 Adoption 时，首次 reconcile 将其归入 `unexplained`，且现有保留机制使其永久滞留。

修复：新增第三种分类 `install-managed`，语义为"当前字节归属可信安装产物"，精确定义与验证条件：

1. 路径必须满足 `is_install_managed_path()`（安装基础设施/适配器/first-use 规则文件；混合所有权文件不在此列）。
2. host 必须存在格式合法的 Install Manifest（`_manifest_format_ok`，kind/ownership/schema 全校验）。
3. 整文件 MANAGED 条目：live 字节 SHA-256 与清单 digest 全等。
4. 混合所有权文件（AGENTS.md/.gitattributes）：managed 区域 live 切片 digest 与 canonical 预期或清单记录一致。
5. hooks.json：live scaffold 片段身份经 `inspect_scaffold_hook_fragment` 校验（无 missing/drifted）。

reconcile 行为（全部保守）：

- 新差异行 + 验证通过 → `install-managed`；验证失败 → `unexplained`（不变）。
- 已有 `unexplained` 行 + 验证通过 → 收敛为 `install-managed`（增量收敛，需充分安装证据）。
- 已有 `install-managed` 行 + 验证失败（篡改/清单失效）→ 降级回 `unexplained`，持久事实不丢失。
- `install-managed` 行在字节回到清单一致时保持；回到 accepted anchor 时按现有 retire 规则退役。
- `unexplained_matches_current()` 将 `install-managed` 与 `unexplained` 同等视为"当前字节有既有归属"——P8 delta/提交门禁语义完全一致（该行仍会以 UNATTRIBUTED→unrelated_delta 呈现给 S2/S3，除非回到 anchor），没有放宽任何门禁。

## 3. 可信安装清单的验证规则

见上节 1-5。核心原则：路径匹配不代表可信；只有清单格式合法 + digest/区域/片段身份逐项验证通过才授予归属；任何验证失败都回落保守分类。

## 4. 旧记录兼容性

- 兼容已有 `unexplained.yaml`：格式校验、schema、record_type 全部不变（schema_version 仍为 "1"，仅新增 classification 枚举值）。
- 旧 `unexplained` 行仅在验证通过时收敛（F3_06 用例证明：安装产物行收敛，非安装行保持 unexplained，无整体赦免）。
- 未修改历史 R7 记录、Gen1→Gen2 Candidate Projection Migration 合同（test_p9 全套 58 passed 佐证）。
- no-SCM Consumer：baseline 与清单一致时恢复字节即 retire（无 drift）；篡改字节保持 unexplained；`_install_managed_verified` 对清单字节 True、篡改字节 False（F3_09）。

## 5. F4 文档改进

`docs/PUBLIC_LIFECYCLE_REFERENCE.md` §2.2 新增五问指引（Intake 声明测试要求 / 绑定 Test Profile / 关联正式 Test Report / 判定 Evidence 对应当前 Candidate / 区分正式与本地测试），全部对照既有接口（`parse_intake_envelope`、`bind_published_evidence`、`develop bind`、`evaluate_ready_for_review`）核验，未开发任何新能力、未强制非空 final_tests、未修改 READY 证据强度合同。

§2.2.1 记录 stale 诊断字段合同（`current_candidate_digest` / `evidence_candidate_digest` / `evidence_report_id` / `evidence_locator` / `remediation`）。

已安装 Consumer 同步：安装产物侧文档由 Consumer UPDATE 的 runtime 刷新分发（P1 TU06/U06 已验证该通道），本轮修改 docs 后安装文档随下次 UPDATE 一致（F4_04 在有本地安装的环境校验逐位一致）。

## 6. F7 诊断改进

两个现有操作边界的拒绝规则全部保持，仅新增诊断信息：

1. `develop complete --test.published_report_id`：报告 stale 时 blockers 原文保留，返回体新增 `stale_evidence = {current_candidate_digest, evidence_candidate_digest, evidence_report_id, remediation}`，经 `published_report_skill_result` 透传到 extras。
2. READY 评估（`evaluate_ready_for_review` → `_judge_requirement`）：stale 拒绝理由附带当前 candidate digest、Evidence 绑定 digest、locator 与 remediation（re-run + rebind，明确不得改写历史决策或删除历史证据）。

Agent 由此可自助识别：当前 Candidate、Evidence Candidate、失效证据/决策、需要 re-run/rebind 的操作。无静默替换、无自动改写、无删除历史。

## 7. 测试命令及结果

新增回归：`python -m pytest tests/test_r7_p2_implementation.py -q`
→ **15 passed, 1 skipped**（skip 项：仓库本身无本地安装时的 F4_04 文档同步）。

定向回归（均通过）：

- `test_r4_maj008_unexplained_drift.py test_r7_p1_implementation.py test_fa2_foundation_amendment_005.py`：101 passed + 1 基线既有失败（见 §8）
- `test_develop_autonomy_lightweight.py test_p7_develop.py test_p7_rev1.py test_p7_rev2.py test_p7_closure.py`：103 passed
- `test_consumer_installation.py test_consumer_self_update.py test_pc_consumer_002.py`：113 passed + 3 subtests
- `test_p6_test.py test_p6_rev1..rev4 test_p6_rev4_closure.py test_p6_supporting_evidence.py test_pc_scf_gate1b_c01.py`：238 passed（7 个 `test_engine` 收集 ERROR 为基线既有 pytest 函数名误收集）
- `test_p8_submit.py test_p8_rev1.py test_p8_rev2.py test_p8_closure.py`：106 passed
- `test_p9_repair_migration.py`：58 passed（R10 为 Windows 并发执行抖动，偶发，见 §8 勘误）

## 8. 与 P1 基线的失败集合对比

全量口径：`python -m pytest tests/ -q --tb=no`（与 P1 基线相同命令、环境与测试选择条件，基线在 `e2dcbfd` 临时 detached worktree 实测）。

独立审计实测数据（以此为准）：

- P2：1956 PASSED / 19 FAILED / 16 ERROR / 2 SKIPPED
- P1 基线：1941 PASSED / 19 FAILED / 16 ERROR / 1 SKIPPED
- 失败及错误用例集合完全一致（PASSED 差额 15 项为 P2 新增测试，SKIPPED 差额 1 项为 F4_04 在无本地安装环境跳过）。

关于 P9_R10（勘误）：`test_P9_R10_concurrent_repair_cas_one_winner` 存在 Windows 并发执行抖动（并发 CAS 场景下的偶发文件写竞争）。实施过程中的单次运行结果（某轮该用例通过/失败）只能反映该次运行的时序巧合，**不得据此推断 P2 修复或引入了该问题**。该用例的偶发行为属基线既有现象，本轮未对其做任何修改。

逐项核对：P2 相对基线新增失败/错误 = 0。全部 19 failed / 16 errors 均为基线既有问题（`test_engine` 命名误收集、`test_pc_consumer_003`、`test_project_import` IMP03/IMP07、FND5_E02 文档断言、P9 文档断言等历史域）。

## 9. 全部剩余问题

- R7 审计矩阵 09/10（合同强度修订）、Session OPEN 阶段提前漂移告警：P3，本轮未实施。
- `install-managed` 行进入 no-SCM baseline 后的差异语义已验证，但 no-SCM 的 Consumer UPDATE 重新生成 baseline 与分类的交互可在 P3 补充用例。
- 基线既有问题（`test_engine` 误收集、pc_consumer_003、IMP03/IMP07、FND5_E02 等）未在本轮修复，属历史域。
- P2 新增测试的 `_adopt` 装置依赖真实 bootstrap apply（约 15s/类），若后续 CI 时长敏感可提取为共享 fixture。

## 10. 候选代码快照

- 分支：`r7-p2-implementation`（未 commit，工作树即快照）
- 修改：`docs/PUBLIC_LIFECYCLE_REFERENCE.md`、`src/scaffold_p6/published.py`、`src/scaffold_p7/lifecycle.py`、`src/scaffold_p7/unexplained.py`、`tests/test_r7_p2_implementation.py`
- 与 P1 发布 commit 的差异：4 文件 +213/-3，1 个新测试文件。

## 11. 独立审计检查点

1. `unexplained.py`：确认 `_install_managed_verified` 不接受路径推断、不接受格式不合法清单；混合所有权文件仅区域切片可验证。
2. `unexplained.py` reconcile：确认 `install-managed`→`unexplained` 降级保留持久事实；`unexplained`→`install-managed` 收敛需验证通过；无整体赦免路径。
3. `unexplained_matches_current`：确认覆盖 `install-managed` 后 P8 delta/provenance 门禁语义不变（建议审计者重跑 `test_r4_maj008` 与 `test_p8_submit`）。
4. `published.py` / `lifecycle.py`：确认所有 stale 拒绝结果与基线一致，仅 reason 文本与新增诊断字段变化（建议对比 `consume_published_report` 返回结构与 `evaluate_ready_for_review` 布尔语义）。
5. 文档：确认 §2.2/§2.2.1 与源码行为逐条一致、未承诺新能力。
6. 测试：确认未修改任何既有测试文件（`git diff --stat` 佐证），新增失败集合为零。

---

## 12. 独立审计结果

- 结论：`R7_P2_INDEPENDENT_AUDIT_PASS`
- F3 / F4 / F7：PASS；COMPATIBILITY：PASS；REGRESSION：PASS
- BLOCKING：0；MAJOR：0；MINOR：2
- `SAFE_TO_COMMIT：YES`

两项 MINOR 均不阻断发布，已随本发布流程记录。除本报告勘误外，未修改任何已通过独立审计的源码或测试文件。

R7_P2_IMPLEMENTATION_COMPLETE
