---
blueprint_version: v1.1
frozen_at: 2026-09-03
revised_at: 2026-09-03
task: spot 出价倍率与保护期参数化
status: frozen
convergence: substantive_converged (csr 4 rounds, 同源+异源; record at workspace/cross-source-review/runs/20260903-133443-spot-bid-params/convergence-record.json)
---

> 修订记录 v1→v1.1（2026-09-03，经用户生产实证授权）：C6 收窄。文档三源（中文官方 API 文档、英文官方 API 文档、CLI 元数据）一致称 SpotDuration 默认值 1，但本项目用户生产实证：未传该参数时实例频繁在 <1h 即因出价被平台回收——隐式默认在生产上未兑现保护期。故 AC-4 的显式 `--SpotDuration 1` 应视为**潜在行为修复**（强制启用文档承诺的保护），而非纯显式化；"默认 '1' 零语义变更"收窄为"文档语义等价，生产行为以 Rollout A/B 实证为准"。成因（RunInstances 路径未应用默认值 / 地域或时段差异 / 文档与实现不符）未能从可获取来源裁决，如实挂账。

# Intent Blueprint: Spot 出价倍率（price multiplier）与保护期（SpotDuration）参数化

## Background（评审发现）

`scripts/select_instance.py` 中 `spot_price_limit = total_price * 1.2` 是**固化魔法数字，且三处重复**：

| 位置                                      | 作用                                   | 状态                     |
| ----------------------------------------- | -------------------------------------- | ------------------------ |
| `scripts/select_instance.py:514`          | 主输出 `SPOT_PRICE_LIMIT`              | 活代码                   |
| `scripts/select_instance.py:534`          | `CANDIDATES_FILE` 每个重试候选行的限价 | 活代码                   |
| `scripts/create_spot_instance.py:207-217` | `calculate_spot_price_limit()` 内      | **死代码**（全仓无调用） |

风险：改一处漏另两处 → 主输出限价与重试时限价不一致；调用方（action 使用者）无法调节出价策略。相邻缺陷：两处活代码均用 `:.4f` 格式化，而 API 约束 `SpotPriceLimit` **最多 3 位小数**（见 S1），如产生 `0.8161` 类 4 位有效小数有被参数校验拒绝的风险（错误码 `InvalidSpotPriceLimit`，见 S1 错误码表；同表另见 `InvalidSpotPriceLimit.LowerThanPublicPrice`——出价低于当前公开价即拒；故 AC-1 对 0<m<1 的 Warning 仅是调用前提示，实际拦截仍由 API 在 RunInstances 时执行（两层独立，前者不蕴含后者）。

## Sources（一手来源摘录，各腿可直接复验）

- **S1 官方 RunInstances API 文档**（https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-runinstances ，本会话 2026-09-03 在线抓取，摘录原句）：
  - SpotDuration（参数表）: "The protection period of the spot instance, in **hours**. Valid values: **1**: After the instance is created, Alibaba Cloud guarantees that the instance will not be automatically released for 1 hour. After 1 hour, the system compares the bid price with the marketplace price in real-time and checks resource inventory to determine whether to retain or revoke the instance. **0**: ... does not guarantee a runtime... **Default value: 1**. Note This parameter currently supports **only the values 0 and 1**. **Spot instances are billed by second.** Select an appropriate protection period based on the execution duration of your tasks. Alibaba Cloud sends a notification through an ECS system event 5 minutes before the instance is revoked."
  - SpotPriceLimit（参数表）: "The maximum hourly price of the instance. This parameter supports up to **three decimal places** and takes effect when SpotStrategy is set to SpotWithPriceLimit."
  - 策略绑定对比（R4 异源发现闭环）：SpotPriceLimit 段落**显式**绑定 SpotWithPriceLimit；SpotDuration 段落**无任何策略绑定子句**（S1 全段在档，对比同表 SpotPriceLimit 的显式绑定）→ SpotDuration 为策略无关（SpotWithPriceLimit 与 SpotAsPriceGo 均适用）；SpotAsPriceGo 路径另由 Rollout 实证闭环。
- **S2a 本机 aliyun CLI 3.4.11 `RunInstances --help` 元数据**（与本仓库实际调用的 API 同一接口，直接相关）："The protection period of the spot instance. Unit: hours... Default value: 1."
- **S2b 同 CLI `CreateInstance --help` 元数据**（另一 API，仅作旁证，不背书 RunInstances）："...You can set this parameter only to 0 or 1."——RunInstances 侧的 0/1 约束由 S1 原句独立成立，不依赖 S2b。
- **S3 本地实证**（本会话，2026-09-03）：向 aliyun CLI（本机 3.4.11）传入不在其元数据中的伪参数 `--TotallyBogusParam 42`，CLI 不在本地做参数校验、直接进入客户端初始化（鉴权）阶段 → CLI 对未知参数不做本地拦截；但"参数被序列化进 RPC 且被服务端接受"未实证，action 固定的 CLI 3.2.2 兼容性由灰度验证闭环（见 Rollout）。
- **S4 仓库源码**：上述三处 1.2 的文件:行号；`action.yml` 的 select/create 两步 env 注入；README.md/README.cn.md 输入表。
- **S1b 官方 ModifyInstanceAutoReleaseTime API 文档**（https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-modifyinstanceautoreleasetime ，2026-09-03 在线抓取）：定时自动释放对 spot 实例可用，原文 "Changes the automatic release time of a pay-as-you-go **or spot instance**"；同页另句原文 "The release time must be at least 30 minutes later than the current time."——AutoReleaseTime 明确支持 spot 实例；RunInstances 侧生效由本仓库 smoke-test.yml 的 "Verify AutoReleaseTime is set (defense line 3)" 步骤（经 DescribeInstances）对真实 spot 实例的生产实证背书；结合本仓库 AutoReleaseTime 兜底（TTL 下限 30min、默认 240min）长期运行于默认 SpotDuration=1 的实例上，C7 获得来源补强（残余推论仍如实标注，见 C7）。
- **S5 编排者在线复核**（2026-09-03，同源腿返回后）：S1 关键句逐句重取命中；S2a `Unit: hours` 复验存在；S1 错误码表含 `InvalidSpotPriceLimit` 与 `InvalidSpotPriceLimit.LowerThanPublicPrice`。
- **S6 历史 Snapshot（Wayback 2023-02-06，help.aliyun.com CreateInstance 文档存档）**：当时即已为小时制——"抢占式实例的保留时长，单位为小时。取值范围：0~~6。保留时长2~~6正在邀测中……取值为0，则为无保护期模式。默认值：1。"；同页 "支持最大3位小数"。现行 0/1 是从 0~6 收窄而来；早期"分钟级取值"的说法无一手来源支持，不采用。

## 核心主张清单（Core Claims — coverage-verified 锚点）

- C1【仓库】1.2 硬编码共三处：select_instance.py 两处活代码 + create_spot_instance.py `calculate_spot_price_limit()`（207-217 行）死代码（无调用方）。
- C2【S1】`SpotPriceLimit` 最多 3 位小数；当前 `:.4f` 有 4 位有效小数风险。
- C3【S1/S2a/S6】`SpotDuration` 单位为**小时**，仅接受 `0` 或 `1`，默认 `1`（现行 S1+S2a；历史 0~6 小时见 S6）。
- C4【S1】Spot 实例**按秒计费**；保护期内提前释放不按 1 小时整收（"Spot instances are billed by second"）。
- C5【S3，收窄】本机 aliyun CLI 3.4.11 实证：CLI 不在本地校验元数据外参数；参数是否透传至服务端未实证，action 固定的 CLI 3.2.2 兼容性待灰度验证（见 Rollout）。
- C6【S1+S2a，v1.1 收窄】现行 API 文档（zh/en/CLI 元数据三源一致）称未传 SpotDuration 时默认 1（1 小时保护）；但本项目用户生产实证：未传参时实例频繁 <1h 被出价回收——隐式默认在生产上未兑现保护。新参数默认 `"1"` 显式传递，应视为对观察问题的修复而非零行为变更；文档等价性与生产行为的差异成因未决，Rollout 含 A/B 验证项。
- C7【S1+S1b】保护期防的是**系统回收**（出价/库存比对）；用户侧释放路径（cleanup / AutoReleaseTime / 自毁）不受影响。S1 原句覆盖系统回收语义；S1b 证明 AutoReleaseTime 对 spot 实例可用（最短 30min）；"TTL<60min 时 AutoReleaseTime 在保护窗口内照常触发"为基于 S1b+仓库生产实况的推论，Rollout 含对应 spot-check。

## Core Use Cases

- UC-1: action 调用者可通过 `spot_price_multiplier` 输入指定出价倍率（默认 1.2，保持现状），倍率同时作用于主输出与全部重试候选。
- UC-2: action 调用者可通过 `spot_duration` 输入指定保护期（默认 "1" = 1 小时防系统回收，等于 API 现行默认；"0" = 无保护期，随时可被系统回收、任务中断风险更高），仅接受 0/1。计费与保护期选择无关（按秒计费，见 C4），不暗示任何价格差异。
- UC-3: 非法取值响亮失败（error_exit 非零退出 + 解释性错误信息），绝不静默钳制。

## 设计决策（显式声明，防误改）

- **倍率在 select_instance 计算，create_spot_instance 保持纯消费**：价格数据在 select 侧，candidates 文件携带预计算限价；倍率 env 只需注入 select 步。`create_spot_instance.py` 的死代码 `calculate_spot_price_limit()` 直接删除（消灭第三处 1.2，而非参数化死代码）。
- **默认值零行为变更**：`spot_price_multiplier` 默认 `"1.2"`；`spot_duration` 默认 `"1"`（== C6 的 API 默认，显式传递只是把隐式变显式）。
- **校验语义（复合模式，round-1 修正归因）**：空串回退默认沿用 `select_instance.py` 的 `MIN_CPU`/`MAX_CPU` 模式（`os.environ.get(...).strip()` + `if str else default`）；非数值/非法域响亮失败沿用 `create_spot_instance.py` 的 `load_ttl_minutes()` 模式（error_exit）。注意：`load_ttl_minutes` 本身对空串是**响亮失败**而非回退默认，不得照抄其取默认值形状。
- **倍率 <1 只警告不阻断**：出价低于市价可能导致创建失败或更快被回收，属合法的风险选择。
- **`:.4f` → `:.3f`**：对齐 C2 的 API 约束（同批顺手修复，因恰好改同一行）。
- **README 双语同步**（`.cursor/rules/04-readme-sync.mdc` alwaysApply）：注明按秒计费、SpotDuration=1 ≠ 最低消费 1 小时。

## Acceptance Criteria (BDD)

- AC-1: `select_instance.py` 新增 `load_price_multiplier()`：env `SPOT_PRICE_MULTIPLIER` 缺省/空串 → 1.2；非数值、≤0 或**非有限值（nan/inf，`math.isfinite` 必须通过）** → error_exit（退出码 1）；0<m<1 → stderr Warning。倍率同时作用于主输出 `SPOT_PRICE_LIMIT` 与 `CANDIDATES_FILE` 每行限价（两处不得再各自硬编码）。
- AC-2: `SPOT_PRICE_LIMIT`、candidates 文件行中限价、及 stderr 调试两行（Total price / Spot price limit）统一格式化为 `:.3f`（≤3 位小数，对齐 API 约束）。若**任一作用点**（主输出或某候选行）计算限价 < 0.0005（格式化将归零为 "0.000"）→ error_exit 响亮失败，绝不发送 0 限价（异常输入，远低于真实市价量级）。
- AC-3: `create_spot_instance.py` 新增 `load_spot_duration()`：env `SPOT_DURATION` 缺省/空串 → 1；必须可解析为 int 且 ∈{0,1}，否则 error_exit 且错误信息包含 "hours" 与 "only 0 or 1"（不提及分钟制历史——见 S6，无一手来源）。
- AC-4: `create_instance()` 增加 `spot_duration: int | None = None` 参数：非 None 时向 RunInstances 命令追加 `--SpotDuration <n>`；None 时不追加。`main()` 两条创建路径（候选重试 + 单次）均传入校验后的值；启动 banner 打印 `Spot Duration: N hour(s)`。
- AC-5: 删除 `create_spot_instance.py` 中无调用方的 `calculate_spot_price_limit()`，模块内不得残留对它的引用。
- AC-6: `action.yml` 声明输入 `spot_price_multiplier`（default `"1.2"`）与 `spot_duration`（default `"1"`），两者均为**裸字符串输入，不得声明 `type: boolean`**（GitHub 对 boolean 输入会把 "0"/空串强转 false，破坏 int 解析）；select-instance 步 env 注入 `SPOT_PRICE_MULTIPLIER`，create-instance 步 env 注入 `SPOT_DURATION`。
- AC-7: README.md 与 README.cn.md 输入表同步新增两行（描述含按秒计费语义），CHANGELOG.md 增加条目。（文档无自动化测试，如实标注：人工核对）
- AC-8: 向后兼容（语义层）：不设置新 env 时，出价策略与保护期语义与现状一致（倍率 1.2；SpotDuration 显式 "1" == 原 API 隐式默认）。**两处有意差异明确枚举、不构成向后兼容违反**：(a) 限价格式 .4f → .3f（AC-2）；(b) RunInstances 命令新增 --SpotDuration 1（AC-4）。test_defaults_preserve_current_behavior 断言语义默认值（multiplier=1.2、duration=1），不得断言 .4f 快照。

## Non-Functional Requirements

- NFR-1: 不新增依赖（仅标准库 + 既有 dev 工具链）。
- NFR-2: `ruff check` 与 `ruff format --check` 干净；`pytest -q` 全绿；测试零网络零凭证。
- NFR-3: env 解析与校验为纯函数或可 monkeypatch 的 loader（沿用 `load_ttl_minutes` 的可测形状），不内联散落。
- NFR-4: README.md/README.cn.md 内容同步（双语规则）。

## Non-Goals

- 不实现 >1 小时保护期（历史版本曾允许 0~6 小时邀测，现行仅 0/1，见 S1/S6）。
- 不修改 TTL/AutoReleaseTime 语义（用户侧释放路径不受保护期影响）。
- 不切换 Spot 策略（SpotWithPriceLimit/SpotAsPriceGo 既有选择逻辑不动）。
- 不做真实账单核验（记入 rollout 人工 spot-check：一次 <1h 提前释放的账单应按秒计）。

## Acceptance-Criteria -> Test Mapping（RED 阶段冻结）

注：`tests/test_select_instance.py` 为**新建模块**（仓库现无此文件）；新用例注释采用蓝图限定编号 `spot-bid AC-N`，避免与既有文件中其他蓝图的 AC-3/AC-4/AC-5（forensics/TTL 蓝图）编号撞车。

- AC-1 → tests/test_select_instance.py::test_price_multiplier_default_and_custom
- AC-1 → tests/test_select_instance.py::test_price_multiplier_invalid_fails_loudly
- AC-2 → tests/test_select_instance.py::test_spot_price_limit_formatted_to_three_decimals
- AC-2 → tests/test_select_instance.py::test_spot_price_limit_below_rounding_floor_fails_loudly
- AC-3 → tests/test_create_spot_instance.py::test_load_spot_duration_validation
- AC-4 → tests/test_create_spot_instance.py::test_run_instances_command_includes_spot_duration
- AC-5 → tests/test_create_spot_instance.py::test_dead_price_limit_helper_removed
- AC-6 → tests/test_action_workflow.py::test_spot_inputs_and_env_wiring
- AC-8 → tests/test_select_instance.py::test_defaults_preserve_current_behavior
- AC-8 → tests/test_create_spot_instance.py::test_spot_duration_defaults_to_one_without_env

用例粒度注（非映射行）：

- test_price_multiplier_invalid_fails_loudly 内含 nan/inf 用例。
- test_price_multiplier_default_and_custom 内含 0<m<1 用例（SPOT_PRICE_MULTIPLIER='0.5' → exit 0、stderr 含 Warning）。
- AC-2 floor 检查作用点 = **两处**：主输出与每个候选行（任一计算限价 < 0.0005 均 error_exit）；test_spot_price_limit_below_rounding_floor_fails_loudly 参数化两个作用点。
- test_spot_price_limit_formatted_to_three_decimals 同时断言 stdout（SPOT_PRICE_LIMIT= 行与 candidates 文件行）与 stderr 调试两行（`Total price: X.XXX`、`Spot price limit: X.XXX`）均为 3 位小数（capsys 双流捕获）。
- test_run_instances_command_includes_spot_duration 参数化两分支（传入 0/1 → 命令含 --SpotDuration；传 None → 命令不含，None 分支另由既有 test_run_instances_command_includes_auto_release_time 的默认调用隐式覆盖）。
- AC-4 双调用点钉扎（**两者都要**，不用或；(a)(b) 均置于 test_run_instances_command_includes_spot_duration 内）：(a) 静态断言 create_spot_instance.py 源码中 create_instance( 的两个调用点均含 spot_duration 实参；(b) 新建 CANDIDATES_FILE fixture 驱动 main() 重试路径——fixture 形状：tmp_path 下写 3 行候选文件（`类型|可用区|vsw-xxx|0.1234|8` 格式），设 env CANDIDATES_FILE=<path> + 必需 env（密钥/区域/VPC/SG/INSTANCE_NAME 等），monkeypatch subprocess.run 捕获 argv，断言重试路径发出的命令含 --SpotDuration。
- test_spot_duration_defaults_to_one_without_env 覆盖单次路径：不设 CANDIDATES_FILE、设必需 env（同重试 fixture 另加 INSTANCE_TYPE、ALIYUN_VSWITCH_ID 及 ALIYUN_IMAGE_ID 或 ALIYUN_IMAGE_FAMILY 之一）、monkeypatch subprocess.run 后驱动 main()，断言 --SpotDuration 1 出现在单次路径命令中且 banner 含 `Spot Duration: 1 hour(s)`。

Coverage Notes：AC-7（README/CHANGELOG 文档同步）无自动化测试，人工核对——不占映射行（映射值必须是收集器可枚举的测试名）。AC 形态采用祈使句规格式（与本仓库 forensics 蓝图一致的家族惯例），Given/When/Then 三段式豁免，可测性不受影响。

## Rollout 验证（实施后）

- 默认参数组合的**语义**行为与现状一致（出价策略 = 1.2×市价；保护期 = 1h）；字节级差异以 AC-8 (a)(b) 枚举为准（限价 3 位小数、命令新增 --SpotDuration 1）。回归测试断言语义同一（loader 默认值 + argv 旗标集合语义），不做字节相等断言。
- 灰度（定义：在可传入非默认 action 输入的调用方 workflow 触发一次真实创建——本仓库 `.github/workflows/smoke-test.yml` 加输入或一次性测试仓库均可）：跑 `spot_duration: 0` + `spot_price_multiplier: 1.5`，核对 banner `Spot Duration: ...` 与实例侧 SpotDuration 生效值（经 DescribeInstances/DescribeInstanceAttribute 核对，具体响应字段以实测为准——smoke-test.yml 已有 DescribeInstances 使用先例）（**闭环 C5**：验证 CLI 3.2.2 确实透传 `--SpotDuration` 并被服务端接受）；一次 <1h 任务提前释放后核对账单按秒计（C4 spot-check）。
- 另跑一次 SpotAsPriceGo 路径（无价格限价场景）+ `spot_duration: 1`：确认 SpotAsPriceGo 下 --SpotDuration 亦被服务端接受（闭环策略无关性证据链）。
- A/B 验证隐式默认行为（**v1.1 新增，闭环 C6 差异成因**）：同区域同规格分别以 v1.3.0（不传 SpotDuration）与 v1.4.0（显式 `--SpotDuration 1`）各创建若干实例，在市价波动窗口对比 <1h 出价中断率；并经 DescribeInstances/DescribeInstanceAttribute 核对 v1.4.0 实例保护生效。若 v1.3.0 对照组同样无中断，则差异成因更可能为时段/地域性，记录归档。
- 另跑一次 `instance_ttl_minutes: 45` + `spot_duration: 1`：核对 AutoReleaseTime 在 1 小时保护窗口内到点照常释放（**闭环 C7 残余推论**）。
