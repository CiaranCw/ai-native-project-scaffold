# 公开生命周期参考（Public Lifecycle Reference）

面向零上下文 Consumer Agent 的公开接口参考。所有字段与行为均对照发布源码核验。

- Intake 信封实现：`src/scaffold_p7/intake.py`（`parse_intake_envelope`、`prepare_proposal`）
- Complete 信封实现：`src/scaffold_p7/engine.py`（`COMPLETE_ENVELOPE_KEYS`、`complete_run_opts`）
- Completion Decision 实现：`src/scaffold_p7/lifecycle.py`
- Test 五态判定实现：`src/scaffold_p6/analysis.py`、`src/scaffold_p6/contract.py`
- Session 状态机实现：`src/scaffold_p7/session.py`

本页描述公开合同。引擎/生命周期权威始终最终裁决合法性；调用方不能制造 READY。

---

## 1. Develop Intake Envelope（任务发布信封）

命令：

```text
python .scaffold/install/run.py enter develop --intake-json-b64 <envelope>
```

信封必须是 JSON 对象，仅接受三个字段（多余字段被拒绝）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `structured_intent` | object | 是 | Agent 对当前人类请求的结构化解释。`kind` 必须为 `develop`；`action` 必须为 `implement` / `plan` / `activate` 之一；`request` 必须携带当前人类请求原文。直接实现（`action=implement`）还要求 `explicit_implementation: true` 且 `authorized_proposal` 与 `proposal` 完全一致。 |
| `proposal` | object | 是 | 有界任务提案，见下表。 |
| `grounding` | object | 是 | 依据声明，见下表。 |

`proposal` 字段（`prepare_proposal` 校验）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `title` | string | 是 | 任务标题。 |
| `goal` | string | 是 | 任务目标。 |
| `acceptance` | string | 是 | 任务级验收标准。 |
| `scope` | object | 是 | `paths` / `modules` / `exclude` / `supporting_paths` 四个字符串列表；`paths` 与 `modules` 至少一个非空；`paths` 与 `exclude` 不得交集。 |
| `stages` | list | 是 | 至少一个 Stage。每个元素：`stage_id`（缺省 `stage-N`）、`goal`、`acceptance` 必填；`required_tests` 可选。`stage_id` 不得重复。 |
| `final_tests` | list | 可选 | 任务级最终测试引用。元素为 `requirement_id`（字符串）或含 `execution_binding: {kind: "test_profile", profile_id}` 的对象；同一 `requirement_id` 的 binding 不得冲突。显式 `profile_id` 必须存在于当前 `tests.yaml` profiles。 |

`grounding` 字段（`assess_grounding` 校验）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `intent_fields` | list[string] | 必须覆盖 `title, goal, acceptance, scope, stages, tests` 全部六项（材料字段由人类意图支撑）。 |
| `knowledge_fields` | list[string] | 必须覆盖 `scope, rules, ownership, tests` 四项（材料字段由项目权威支撑）。 |
| `uncertainties` | list[string] | 非空即阻断（NEEDS_HUMAN）。 |
| `material_decisions` | list[string] | 非空即阻断（NEEDS_HUMAN）。 |

最小合法样例（direct activation，发布即 `IN_PROGRESS`）：

```json
{
  "structured_intent": {
    "kind": "develop",
    "action": "implement",
    "explicit_implementation": true,
    "request": "为用户服务添加邮箱格式校验并补充测试",
    "authorized_proposal": {
      "title": "用户服务邮箱校验",
      "goal": "注册与资料更新入口拒绝非法邮箱",
      "acceptance": "非法邮箱被拒绝；新增单测覆盖合法/非法样例；现有用户服务测试全部通过",
      "scope": {"paths": ["src/services/user.py"], "modules": [], "exclude": [], "supporting_paths": ["tests/test_user.py"]},
      "stages": [
        {"stage_id": "stage-1", "goal": "实现校验并补测试", "acceptance": "新增测试通过且既有测试不回归", "required_tests": []}
      ],
      "final_tests": []
    }
  },
  "proposal": {
    "title": "用户服务邮箱校验",
    "goal": "注册与资料更新入口拒绝非法邮箱",
    "acceptance": "非法邮箱被拒绝；新增单测覆盖合法/非法样例；现有用户服务测试全部通过",
    "scope": {"paths": ["src/services/user.py"], "modules": [], "exclude": [], "supporting_paths": ["tests/test_user.py"]},
    "stages": [
      {"stage_id": "stage-1", "goal": "实现校验并补测试", "acceptance": "新增测试通过且既有测试不回归", "required_tests": []}
    ],
    "final_tests": []
  },
  "grounding": {
    "intent_fields": ["title", "goal", "acceptance", "scope", "stages", "tests"],
    "knowledge_fields": ["scope", "rules", "ownership", "tests"],
    "uncertainties": [],
    "material_decisions": []
  }
}
```

结果：完全 grounded 且 `action=implement` 直接通过时发布 `IN_PROGRESS` Task 并返回
`COMPLETED`（`next_route=develop.normal_task`）；否则发布 `DRAFT` 并返回
`NEEDS_HUMAN`。Intake 不创建 Develop Session、不修改源码、不授权 Commit/Push/Submit。

---

## 2. Develop Complete Envelope（完成请求信封）

命令：

```text
python .scaffold/install/run.py develop complete --task-id <task-id> --complete-json-b64 <envelope>
```

前置条件：该 Task 已有绑定它的 OPEN Develop Session（`develop session` 打开）。
complete 永远不创建 Session；成功处理后该 Session 会自动 SEALED（见 §3）。

信封必须是 JSON 对象，仅接受五个白名单字段（未知字段整体拒绝）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `test` | object | 可选。白名单子键：`invoke`（bool，同步调用一次 Test）、`published_report_id`（string，消费已发布的 P6 报告）、`selected`（list[string]，profile 选择）。`invoke` 与 `published_report_id` 互斥；三者均缺省表示本信封不涉及 Test。 |
| `stage_decision` | object | 可选。Stage Completion Decision 规范，必须绑定恰好一个 Stage（`stage_id` 必须与该 Stage 一致且唯一存在）。结构见 §2.1。 |
| `stage_decisions` | list[object] | 可选。批量 Stage Completion Decision（P3-F5）。每个 decision 仍是结构同 §2.1 的单个 Stage 绑定规范，必须精确绑定一个真实存在的 Stage。原子性：任一 decision 非法（绑定不存在/歧义 Stage、重复 `stage_id`、与单数 `stage_decision` 绑定同一 Stage 冲突、结构非法）时整个信封被拒绝，Task 不发生任何部分发布。所有 decision 仍走既有 Candidate、Evidence 与 Completion 门禁；与 `task_decision`、`ready` 的组合遵守现有生命周期。单数 `stage_decision` 永久兼容，两者可并存但不得绑定同一 Stage。 |
| `task_decision` | object | 可选。Task Completion Decision 规范，结构同 §2.1（无 `stage_id`）。 |
| `complete_stage` | bool | `true` 表示请求把当前 IN_PROGRESS Stage 推进到 COMPLETE（仍由决策与证据合法性裁决）。与 `stage_decision` 可同用；仅有 `stage_decision` 时隐含 complete 请求。 |
| `ready` | bool | `true` 表示请求 READY_FOR_REVIEW（Records §11 门禁裁决）。 |

空信封、不含任何生命周期操作的信封均被拒绝。

### 2.1 Completion Decision 结构

| 字段 | 说明 |
| --- | --- |
| `stage_id` | （仅 Stage Decision）必须精确绑定一个存在的 Stage。 |
| `candidate_digest` | 可选。缺省由引擎盖当前 candidate 戳；显式提供且不等于当前 candidate 时记录为 stale 决策（不得支撑 COMPLETE/READY）。 |
| `outcome` | `SATISFIED` / `UNSATISFIED` / `UNKNOWN`（未知值归一为 UNKNOWN）。请求 SATISFIED 时引擎逐条校验 basis，不满足则降级为 UNKNOWN。 |
| `basis` | list。允许 kind：`test_evidence` / `ci_evidence` / `external_evidence` / `human_observation`（引用类，必须携带 `evidence_ref.locator` 可移植 P6 locator 且报告 current）或 `task_fact`（文字摘要）。禁止 kind：`chat` / `user_statement` / `session_memory` / `raw_report`（出现即无法 SATISFIED）。空 basis 回退为一条 task_fact 并使 SATISFIED 降级为 UNKNOWN。basis 中内嵌 report 原文的条目被丢弃。 |
| `rationale` | string，可省略（有默认文案）。含 "user said" / "in chat" 的理由使 SATISFIED 降级为 UNKNOWN。 |

### 2.2 Evidence Locator 用法

- Task proposal 的 `required_tests` / `final_tests` 元素可携带
  `execution_binding: {kind: "test_profile", profile_id}`。Test 执行后，
  引擎自动把 portable locator 按 producer profile 回写绑定
  （`bind_published_evidence`）；也可事后用
  `develop bind --task-id <id> --requirement-id <id> --profile-id <id>` 补挂。
- 决策 basis 引用类条目写法：
  `{"kind": "test_evidence", "summary": "...", "evidence_ref": {"locator": "<portable P6 locator>"}}`。
- READY 评估（`evaluate_ready_for_review`）逐条解析 Stage `required_tests`
  与 Task `final_tests` 的 locator：resolve 失败、candidate 不 current、
  producer profile 与 binding 不符均阻断。**空集视为通过**——这是合法但较弱的
  配置；建议在 proposal 中声明真实 required 测试。

零上下文 Agent 的结构化测试绑定指引（全部对照源码核验）：

- **如何在 Intake 中声明测试要求**：在 proposal 的 `stages[].required_tests`
  （Stage 级）与 `final_tests`（Task 级）写入测试要求。每个元素最小形态是
  `{"requirement_id": "<id>"}`；声明 `execution_binding` 后，Test 完成时
  引擎自动回填 `evidence_ref.locator` 与 `observed_outcome`，无需 Agent
  手工拼接 locator。显式 `profile_id` 必须存在于当前 `tests.yaml` profiles。
- **如何绑定已有 Test Profile**：先在 `understand refresh` 产出的
  `tests.yaml` profiles 中确认目标 profile 存在，再写
  `execution_binding: {kind: "test_profile", profile_id: "<id>"}`。
  `kind` 必须精确为 `test_profile`；binding 冲突（同一 requirement_id
  两个 profile）会被拒绝。
- **如何关联正式 Test Report**：两条合法路径——(a) Intake 时声明了
  execution_binding，`develop complete` 的 `test.invoke: true` 同步执行后
  `bind_published_evidence` 自动把 portable locator 挂到对应 requirement；
  (b) 已有报告时用 `develop bind --task-id <id> --requirement-id <id>
  --profile-id <id>` 补挂，或 complete 时用 `test.published_report_id`
  消费既有报告。
- **如何判断 Evidence 对应当前 Candidate**：对每个 locator，
  引擎 resolve 时校验报告绑定的 `candidate.candidate_digest` 与当前
  workspace candidate（含 projection generation 兼容）一致；不一致即
  "stale for the actual candidate"，该条目无法支撑 COMPLETE/READY。
  此时正确动作是重新执行 Test（`test.invoke: true`）或对当前 candidate
  重新绑定，而不是改写历史决策。
- **如何区分正式 Scaffold Test 与额外执行的本地测试**：正式 Test 是经
  P6 公开边界执行并发布 `report_id` 的 scoped 验证运行（见 §7）；Agent
  在 Session 内自行跑的本地构建/测试命令（如直接 `pytest`）不是 P6
  Evidence，不能写入 `evidence_ref`，只能作为过程参考披露。

### 2.2.1 Stale Evidence 诊断字段

当 required/final 测试引用的 Evidence 不再对应当前 Candidate 时，拒绝
信息携带以下结构化诊断（便于零上下文 Agent 自助恢复，不改变拒绝结果）：

| 字段 | 含义 |
| --- | --- |
| `current_candidate_digest` | 当前 workspace candidate 的 digest。 |
| `evidence_candidate_digest` | 被拒 Evidence 报告绑定的 candidate digest。 |
| `evidence_locator` | 失效 Evidence 的 portable locator。 |
| `remediation` | 恢复指引：`re-run Test against the current candidate and rebind`。 |

同一诊断同样出现在消费 Published Test Report 的两个边界上：
`develop complete` 的 `test.published_report_id` 路径，以及
`refresh_ready_authority` 路径——报告过期时 blockers 携带
`current_candidate_digest` / `evidence_candidate_digest` / `remediation`，
且历史报告与历史决策永不被改写或删除。

### 2.3 最小合法样例（Test + Stage 决策 + READY）

```json
{
  "test": {"invoke": true},
  "stage_decision": {
    "stage_id": "stage-1",
    "outcome": "SATISFIED",
    "basis": [
      {"kind": "test_evidence", "summary": "scoped 验证通过", "evidence_ref": {"locator": "p6://<report-id>/profile/<profile-id>"}}
    ],
    "rationale": "实现完成且 required 测试通过"
  },
  "task_decision": {
    "outcome": "SATISFIED",
    "basis": [
      {"kind": "test_evidence", "summary": "final 测试通过", "evidence_ref": {"locator": "p6://<report-id>/profile/<profile-id>"}}
    ]
  },
  "complete_stage": true,
  "ready": true
}
```

---

## 3. Session 状态机（OPEN / SEALED / ABORTED）

- Develop Session 只有三种终态行为：`develop seal`（成功收口，含变更对账）、
  `develop abort`（放弃），以及 complete 成功处理后的**自动 SEALED**。
- 状态转换不可逆：OPEN → SEALED / ABORTED，不存在重新打开。
- 成功的 complete（含 READY 发布路径）处理完成后 Session 即 SEALED
  （`engine.py` READY 发布路径调用 `seal_session`）；后续操作需要新的 Session。
- SEALED Session 目录是只读证据，由 Submit S12 阶段清理。
- Task 级生命周期独立演进：`IN_PROGRESS` → `READY_FOR_REVIEW`（CAS 发布）；
  READY Task 仅可经 Stage 定向的 `submit_to_develop` handoff 重开进 repair。

## 4. Session 状态查询（已有公开方式）

```text
python .scaffold/install/run.py understand refresh --action resume
```

输出 JSON 的 `work.sessions` 字段枚举全部 Develop Session 及其状态
（含 OPEN/SEALED/ABORTED/UNKNOWN/ORPHANED/MALFORMED）。resume 是观测性命令，
不依赖聊天历史。

### 4.1 Session 状态统计（P3）

`work.session_status_counts` 基于同一实时权威枚举（`inspect_sessions()`）
提供按状态统计，不新增第二套 Session 权威记录：

- `counts`：`OPEN` / `SEALED` / `ABORTED` / `UNKNOWN` 四类计数；
- `anomalous`：实际存在的异常重建 Session（`ORPHANED` / `MALFORMED` /
  `UNREADABLE` / 身份非法）逐条保留 `record_id` + `status` +
  `reconstruction` 明细，不会被统计静默删除；
- 统计来源标注为 `inspect_sessions live enumeration`——只来自实时权威枚举，
  不通过历史聊天内容或缓存推断。

### 4.2 Resume 只读化（P3-F6）

正常 `resume` 观测过程**不修改 `progress.json` 或其他持久文件**：
resume 路径的心跳只输出到终端 stderr（文本格式与 WORKING 心跳一致），
不再写 `.scaffold/runtime/progress.json`。全局 Progress 机制本身保留，
其他需要持久进度记录的长时间运行操作（Test 执行、Session 打开/关闭等）
行为不变。重复 resume 幂等：两次 resume 之间持久文件字节一致。

### 4.3 Session OPEN 提前漂移诊断（P3-F7）

`develop session` 成功打开 OPEN Session 时，结果 extras 携带只读诊断
`drift_warning`（`status`: NONE / DIVERGED / UNKNOWN），检查当前 Candidate
与适用的最近有效 SEALED 证据之间的关系：

- Candidate 绑定一致性：OPEN Session 记录的 candidate digest 与当前
  workspace Candidate 是否一致；
- 未归属漂移：Task scope 之外的未跟踪/已修改工作树文件（Task 范围内的
  合法授权开发变化与 OPEN Session 自身合法写入不产生告警）；
- 最近 SEALED 证据关系：最近 SEALED Session 记录的 Candidate 与当前
  Candidate 不一致时提示（权威的 stale 判定仍由既有 Evidence 门禁在
  消费时做出，本诊断不重复也不替代 P2 的 Published Evidence Staleness
  检查）。

边界：诊断是提前提示，不修改、不删除任何历史 Evidence；SCM 观测不可用
或 Session 未记录 candidate digest 时明确报告 UNKNOWN，不伪造 Candidate
身份；既有历史差异以提示形式呈现，由 Agent 判断归属。

## 5. Test 五态关系（TEST_PASS / coverage_complete / required_policy / TEST_COMPLETE / READY）

| 概念 | 含义 | 判定来源 |
| --- | --- | --- |
| `test_pass`（TEST_PASS） | 本次执行的批次全部 PASS 且 candidate 匹配、证据完整、无 contract blocker。批次结果属性，不涉及 required 集。 | `analysis.py` |
| `coverage_complete` | required 覆盖完整（`required_coverage_complete`）且被选中的 optional 也完整。 | `analysis.py` |
| `required_policy` | `VERIFIED` ⇔ required 集权威（`required_set_authoritative`）；否则 `UNKNOWN`。 | `analysis.py` |
| `test_complete`（TEST_COMPLETE） | `required_coverage_complete 且 required_fail==0`，且**仅在 required 集权威时可能为 true**。required 集为空且顶层未声明 `required_authority: VERIFIED` 时恒为 false。 | `analysis.py` |
| READY_FOR_REVIEW | Records §11 评估器：Task 结构完整（全部 Stage COMPLETE）+ 各 Stage required_tests 与 Task final_tests locator 逐条可解析且 current + Stage/Task Completion Decision SATISFED 且 current。**评估器不直接读 TEST_COMPLETE**。 | `lifecycle.py` |

重要边界（不得误读）：

- TEST_COMPLETE=false **不必然**阻止 READY。只有当 READY 请求同时消费
  published Test report（`test.published_report_id` 路径）或走
  `refresh_ready_authority` 路径时，引擎才硬性要求该报告 `test_complete=true`。
- 不得把空 required 集自动视为权威来"达成" TEST_COMPLETE——这会削弱测试门禁。

### 5.1 S5 权威诊断（authority_blockers）

当 Submit 在 S5 因 required 集不权威而阻断（TEST_COMPLETE=false）时，结果
`extras.authority_blockers` 携带结构化恢复指引，逐条说明：

1. **为什么 TEST_COMPLETE 为 false**：报告的 `required_policy` 为
   `UNKNOWN`（required 集未经项目权威确认），S5 无法对照一个无根据的
   required 集验证完整性；
2. **谁拥有修正权威**：required 集权威存在于 `.scaffold/tests.yaml`，该文件
   是 GENERATED，仅由 Understand Refresh 维护；Develop 与 Submit 均不得手工编辑；
3. **缺什么 grounded 信息**：空 required 集缺顶层 `required_authority: VERIFIED`
   声明（或 grounded 的零 required 事实）；非空 required 集缺各 profile 的
   `required_authority: VERIFIED` 事实。

恢复路径（全部自主，无人工审批门）：运行 Understand Refresh grounded
required profiles（或 zero-required 事实）→ 重跑 Test 产出新报告 → 重新 Submit。
该诊断只解释阻断原因，不改变 TEST_COMPLETE 判定语义。

## 6. tests.yaml required 权威升级路径

`tests.yaml` 的 `required_authority`（顶层与每个 profile）取值为事实类
（UNKNOWN / VERIFIED 等）。required 集权威判定（`contract.py`
`_required_set_is_authoritative()`）：

1. 契约（tests.yaml）confidence 必须为 `VERIFIED`；
2. 每个 required profile（`required: true`）的 `required_authority` 必须
   显式为 `VERIFIED`；
3. required 集为空时，必须存在顶层 `required_authority: VERIFIED` 声明，
   否则 required 集不权威。

升级路径：Understand Refresh 重新发现命令/测试后，在确认某 profile 的命令
真实可执行且属项目权威测试面时，将该 profile 的 `required: true` 与
`required_authority: VERIFIED` 写入 tests.yaml（并按需声明顶层
`required_authority`）。该文件按 project.yaml ownership 规则维护
（GENERATED 索引可由 Refresh 重写；人工确认后视为权威）。升级完成后，
后续 Test 报告的 `required_policy` 变为 `VERIFIED`，`TEST_COMPLETE` 才可能为 true。

S5 恢复可用性（R8-FND-D）：Submit S5 因 required 集不权威而阻断时，
阻断结果的 `extras.authority_blockers` 携带结构化诊断——说明阻断原因
（required_policy 为 UNKNOWN）、修正权威归属（tests.yaml GENERATED，
仅 Understand Refresh 维护）、缺失的 grounded 信息，以及自主恢复路径
（Refresh → 重跑 Test → 重新 Submit）。整个恢复过程无需人工审批门；
语义约束不变：required 集不权威时 TEST_COMPLETE 恒为 false。

## 7. 测试口径与交付报告规范（F9）

Agent 在对外交付报告中必须区分以下测试类别，不得混同：

- **正式 Scaffold Test**：经 P6 公开边界执行并发布 `report_id` 的 scoped
  验证运行，是 Completion Decision 与 READY 的合法证据来源。
- **Scaffold 外部执行的本地测试**：Agent 在 Task 执行中自行运行的本地构建/
  测试命令（如直接 `pytest`），其结果不是 P6 Evidence，不能作为决策依据，
  只能作为过程参考披露。
- **聚焦测试**：仅针对本 Task scope 的子集执行（`test.selected`）。
- **全量项目测试**：项目全部测试面；耗时长，其通过与否不能替代 scoped
  正式验证的结论，反之亦然。
- **尚未执行或无法验证的测试**：必须明确声明"未执行"及原因，不得暗示已验证。

交付报告必须披露影响验收的重要异常（intake 重试、环境故障、被跳过的验证、
类型修补等），不能只报告最终成功结果。

## 8. Git Commit 与 Git Push 授权

Git Commit 与 Git Push 是独立的发布操作，各自需要当前显式用户指令。
Scaffold 的 shell 硬边界对 `git commit` / `git push` 直接拒绝
（`shell_boundary.py` `GIT_PUBLICATION`），history-rewriting 操作
（rebase/reset/clean/force-push 等）同样被拒。其余正常开发操作（含首次
Adoption apply）自主执行，无需人工审批。

### 8.1 丢弃型 Git 操作的自动防护（P3-F8）

在上述人工授权合同不变的前提下（只有 Commit/Push 需要人工授权），
shell 边界对丢弃型 Git 操作增加**自动风险判断**，不引入任何额外人工审批：

- `git checkout -- <paths>` / `git checkout <tree-ish> -- <paths>`、
  `git restore [<paths>]`（worktree restore）、以及 `git reset --hard`
  （既有 GIT_DESTRUCTIVE 边界）会不可逆丢弃工作树未提交内容，自动阻断，
  并说明具体风险与非破坏性替代路径（先记录当前内容或完成授权 Commit 再
  重新应用丢弃）。
- 普通分支/提交切换（`git checkout <branch>`、`git checkout -b`）与全部
  检查类命令（status/log/diff/show）不受影响，保持自主执行。
- Agent 会话之外用户直接执行的 Git 命令不在本机制约束范围内。
