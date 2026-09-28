# P1 实施说明（R7 Findings F1 / F2 / F9）

- 日期：2026-09-25
- 基线：发布 commit `b34b3dba8eabb18f51f6b7a7847ea160b4187e5d`
- 工作树：`F:\NewResearch\scaffold-r7-p1-implementation`（分支 `r7-p1-implementation`）
- 产品授权要求（本轮）：只有 Git Commit 与 Git Push 需要分别获得用户明确授权；其余正常开发操作（含首次 Adoption）均自主执行，无需人工审批。

---

## 1. 关键核对结论（实施前源码核对）

发布基线上，代码执行路径已经具备自主 Adoption 能力：

- `scaffold_p5/engine.py` `_adoption_apply_requested()`：只要 `approval_matches()`
  （`--approved` + 64 位 `plan_digest` 与当前 Plan 一致）即视为合法 apply 请求，
  不检查也不要求任何人工审批。
- `scaffold_p5/first_use.py` `classify_first_use_shell()`：对
  `understand bootstrap --approved --plan-digest <hex>` 组合返回
  `SHELL_ALLOW`（ASK_APPLY_REASON），即 Cursor hook 层不会对该命令产生
  `permission=ask` 人工审批。
- `scaffold_p5/result.py` `adoption_approval_human_gate()` 已写明
  "No human approval is required for Adoption"。

F1 的真实缺陷在展示层与持久化层：

1. 多处正式合同文本与安装产物宣称"需人工批准/审查"（`consumer_install.py`
   RC2_CONSUMER_AGENTS_INNER L148、`docs/architecture/ADOPTION_FLOW.md`
   B4 节、`FIRST_USE_ENFORCEMENT_DESIGN.md` L186-193 等），与实际行为不一致，
   会误导零上下文 Agent 在 Adoption 处主动停下等待审批。
2. `persist_session()` 写出的 Adoption Session 只有
   `plan.observed_approved: true`，没有任何授权依据字段，无法审计本次 apply
   的授权来源（R7 审计矩阵 01）。

## 2. F1 改动清单

### 2.1 授权依据持久化（增量字段，不改既有字段）

- `scaffold_p5/adoption.py`
  - 新增常量 `AUTHORIZATION_KINDS = {standing_policy, agent_asserted, human_instruction, client_confirmation}`。
  - `persist_session()` 新增关键字参数 `authorization_basis`（dict 或 None），
    写入 session 的 `plan.authorization_basis = {kind, location, recorded_at}`。
    `location` 只记录真实的依据位置（如 AGENTS.md 托管路由区的常设预授权条款），
    禁止伪造人工授权。
  - 引擎层默认依据为 `standing_policy`：Understand bootstrap 合同中的常设预授权
    条款（`skills/understand/SKILL.md` bootstrap 节 + AGENTS.md 托管路由区）。
  - `update_session()` 增加对旧版 session（无 `authorization_basis` 字段）的读取
    兼容：字段缺失视为未记录，不做任何回填或伪造。
- `scaffold_p5/engine.py`
  - `_adoption_apply_requested()` 在 apply 请求被受理时构造默认依据
    `{kind: standing_policy, location: STANDING_POLICY_LOCATION,
    recorded_at: iso_now()}` 写入 `extras["apply_request"]["authorization_basis"]`
    （调用方显式传入 `authorization_basis` 选项时优先使用显式值）。
  - `_apply_adoption()` 调用 `persist_session(..., authorization_basis=...)`、
    `_replan_adoption()` 调用 `replace_session_plan(..., authorization_basis=...)`
    时从 `extras["apply_request"]` 透传该依据。
- Adoption Session schema_version 保持 `"1"`（新增字段向后兼容读取）。

### 2.2 授权文案统一（改为"自主执行"）

按新的产品授权要求，将以下文本中的"需人工批准"表述改为"Agent 自主执行"：

- `scaffold_p5/consumer_install.py` RC2_CONSUMER_AGENTS_INNER：
  "Preview is not approval. Stop for explicit human approval..." 改为
  "Continue with `--approved --plan-digest` of that exact Plan. Adoption apply
  is Agent lifecycle work; no human approval is required. It is not Git Commit
  or Push."
- `docs/architecture/ADOPTION_FLOW.md`：
  - 头部边界段：删除 "explicit human Plan approval" 与
    "authorized only by permission=ask" 表述，改为 Agent 自主 apply +
    authorization_basis 留痕。
  - B4 节改名 `B4 Plan Apply Authorization`，default = Agent 自主
    （standing_policy 依据），不再宣称 "default = not authorized"。
  - Approval and re-plan loops 节改写为 Plan apply authorization 循环
    （material change 仍触发 re-discover / re-plan，新的 apply 请求重新记录依据）。
- `docs/implementation/FIRST_USE_ENFORCEMENT_DESIGN.md`：
  同步授权来源枚举与"apply request 非 human provenance"的表述保持一致
  （本节为设计说明，不改变行为）。

保留不变：`skills/understand/SKILL.md` 与全部 skill.yaml 完全未改动——
bootstrap 节本来就声明了常设预授权条款，无需修改；保持四个 Skill 包的
package_digest 与发布基线逐位一致（见 §5）。

保留不变：NOT_ADOPTED 边界（Bootstrap 完成前普通产品代码修改仍被
`first_use.py` hook 拒绝）；Plan 一致性（digest 匹配）、CAS、Ownership、
生命周期检查；Commit/Push 独立授权（`shell_boundary.py` `GIT_PUBLICATION`
硬边界不变）。

## 3. F2 改动清单（公开生命周期文档）

新增 `docs/PUBLIC_LIFECYCLE_REFERENCE.md`（公开参考页，分发面随 Distribution
checkout，可通过仓库内相对路径被零上下文 Agent 发现；安装产物侧由 Cursor
适配器与 AGENTS 托管区指向该页）。内容全部对照源码核验：

- Intake Envelope 字段表（`scaffold_p7/intake.py parse_intake_envelope`）：
  `structured_intent`（必填 mapping，kind=develop，action=implement/plan/activate）、
  `proposal`（title/goal/acceptance/scope/stages/final_tests，含
  execution_binding.profile_id 可选绑定）、`grounding`（intent_fields/
  knowledge_fields/uncertainties/material_decisions）+ 最小合法样例。
- Complete Envelope 字段表（`scaffold_p7/engine.py COMPLETE_ENVELOPE_KEYS`）：
  `test`（invoke/selected/published_report_id 三键白名单，invoke 与
  published_report_id 互斥）、`stage_decision`（单 Stage 绑定，
  stage_id/candidate_digest/outcome/basis/rationale）、`task_decision`、
  `complete_stage: true`、`ready: true` + 最小合法样例。
- Stage/Task Completion 流程与 basis kind 规则（`lifecycle.py`）：
  `EVIDENCE_BASIS_KINDS`（test_evidence/ci_evidence/external_evidence/
  human_observation）、`FORBIDDEN_BASIS_KINDS`（chat/user_statement/
  session_memory/raw_report）、空 basis 回退 task_fact、
  SATISFIED 需要 portable locator 且报告 current。
- Session OPEN/SEALED/ABORTED 行为（`session.py seal_session` /
  `engine.py` seal/abort 路径）：成功 complete 处理后 Session 自动 SEALED、
  不可逆；SEALED Session 目录由 Submit S12 清理。
- 已有公开 Session 状态查询：`understand refresh --action resume` 输出的
  `work.sessions`（`resume.py inspect_sessions()`），含状态枚举。
- 五态关系表（`scaffold_p6/analysis.py` + `scaffold_p7/lifecycle.py`）：
  TEST_PASS / coverage_complete / required_policy / TEST_COMPLETE / READY 的
  实际关系。明确：READY 评估器不直接读 TEST_COMPLETE；只有
  "READY 请求同时消费 published report / refresh_ready_authority" 路径
  （`engine.py` L1510/L2055/L2506 三处硬阻断）才要求 test_complete=true；
  空且非权威 required 集时 TEST_COMPLETE 恒 false；不得把空 required 集
  自动视为权威。
- required_tests/final_tests 与 Evidence Locator 用法：Task schema
  `execution_binding: {kind: test_profile, profile_id}`、portable locator、
  `develop bind` 命令、`bind_published_evidence` 自动绑定通道。
- tests.yaml required 权威升级路径：顶层与 per-profile `required_authority`
  从 UNKNOWN 升级 VERIFIED 的条件（`scaffold_p6/contract.py`
  `_required_set_is_authoritative()`：契约 confidence=VERIFIED 且每个
  required profile 显式 VERIFIED；空集需顶层 `required_authority: VERIFIED`）。

F9（报告口径）作为该文档的一节：区分正式 Scaffold Test / 外部本地测试 /
聚焦测试 / 全量项目测试 / 未执行测试；交付报告必须披露影响验收的重要异常。

## 4. 测试

新增 `tests/test_r7_p1_implementation.py`：

- TU01 文档断言：PUBLIC_LIFECYCLE_REFERENCE 存在且包含关键小节标题；
- TU02-TU04 信封样例逐字段被实际 CLI 接受（intake envelope 经
  `parse_intake_envelope`、complete envelope 经 `complete_run_opts`）；
- TU05 authorization_basis 落盘（standing_policy 依据、含 location）；
- TU06 旧版 adoption session（无新字段）读取不报错；
- TU07 NOT_ADOPTED 普通业务修改仍被拒（回归）；
- TU08 digest 不匹配的 apply 仍被拒（回归）；
- TU09 hook 对 digest-bound apply 返回 allow（自主，无 ask）；
- TU10 Commit 未授权被拒、Push 被拒（GIT_PUBLICATION 硬边界回归）；
- TU11 旧合法生命周期行为回归：agent_apply_request allow、
  NOT_ADOPTED 时 preview 后 host 仍 NOT_ADOPTED；
- TU12 安装产物可发现性：RC2_CONSUMER_AGENTS_INNER 含公开参考页指引与
  自主 Adoption 文案。

运行方式：`python -m pytest tests/test_r7_p1_implementation.py -q`，
34 passed（13 项核心 TU + 21 项新增集成测试：安装/UPDATE/Parity 三类）。

既有回归（均在本 worktree 实测通过）：

- `tests/test_first_use_enforcement.py`：56 passed；
- `tests/test_project_import.py` + `tests/test_consumer_installation.py`：
  86 passed, 3 subtests passed。勘误：`test_project_import.py` 的
  IMP03/IMP07 实际未修改——该文件已恢复发布基线原文，本轮不存在对
  IMP03/IMP07 断言的任何改动；两用例在基线 b34b3db 上即因旧断言
  `permission == "ask"` 与基线 allow 行为的历史矛盾而失败，属基线既有
  问题，本轮不通过修改测试断言虚构行为变化。四个 Skill 包的
  package_digest 与发布基线逐位一致由 EXPECTED_PACKAGES 断言
  （位于通过的其他用例）独立证明。

## 5. 兼容性与 Skill 包身份决策

- Skill 包版本保持 `understand@2.1.0 / develop@2.1.0 / test@2.0.1 /
  submit@2.1.0` 不变。理由：本轮未修改任何 skill.yaml/SKILL.md 的
  正式合同语义——SKILL.md bootstrap 节本来就声明了常设预授权（本轮只是
  在文档/展示层把与行为不一致的"需人工批准"文案统一掉）；升 PATCH 会
  改变 package_digest，导致已安装 Consumer 的 skills.lock 预期身份失配
  （`packages.py exact_match` 全等比较），需要全量 Consumer update 才能收敛，
  收益为零。改动面全部在 src/docs 层，随 Consumer UPDATE 的 runtime 刷新分发。
- Gen1→Gen2 迁移机制、四 Skill 架构、Task Book / Develop Session /
  Change Record 权威职责、Candidate/Evidence/Ownership/READY 门禁全部未触碰。

## 6. 全量回归口径（勘误补充）

全量回归（`python -m pytest tests/ -q`，排除 test_pc_consumer_003.py 与
test_project_import.py 两个已单独核对的套件）实测：
1915 passed, 19 FAILED, 16 ERROR。该 19 FAILED / 16 ERROR 全部为基线
既有问题（P7/P9/FA2 等历史域），已在基线 b34b3db 临时 worktree 上
逐项运行核对：失败/报错用例清单与基线完全一致，无一新增、无一消失。
test_pc_consumer_003.py 的 10 项失败集合亦与基线逐项一致
（identical: True）。历史存量测试失败不属于本轮新增回归，未为全绿而
临时修改或排除任何测试。

## 7. 剩余问题

- R7 审计矩阵 08（install manifest → drift 分类打通）、09/10（合同强度
  修订）、11（批量 stage decision）、12（resume 副作用）属 P2/P3，本轮不改。
- `authorization_basis.kind=human_instruction / client_confirmation` 的
  生产级落盘入口（如 Cursor hook 确认事件透传）留待后续版本；当前只有
  standing_policy 与 agent_asserted 两种真实来源。
