---
blueprint_version: v2
frozen_at: 2026-09-03
revised_at: 2026-09-03
task: spot 出价倍率与保护期参数化
status: frozen
convergence: v1 substantive_converged (csr 4 rounds; record at workspace/cross-source-review/runs/20260903-133443-spot-bid-params/convergence-record.json); v1.1 delta 经用户生产实证授权（2026-09-03，未单独跑 csr）；v1.1+v2 全文经 spot-strategy-v2 run 3 轮评审 substantive_converged（record: workspace/cross-source-review/runs/20260903-163050-spot-strategy-v2/convergence-record.json，cap=2 经人工授权扩至 3）
---

> 修订记录 v1.1→v2（2026-09-03，经用户需求授权）：新增 UC-4 与 AC-9..AC-12——`spot_strategy` 输入支持显式自动出价（SpotAsPriceGo），优先于倍率：显式设置后命令不带 --SpotPriceLimit，倍率/限价不参与竞价（但输入仍全量校验）。默认 "SpotWithPriceLimit"。选型逻辑零改动；v1 遗留 Non-Goal"不切换 Spot 策略"同步收窄为"仅缺省路径回退不动"；AC-8 差异枚举增补 (c)(d) 两项（无限价 error_exit、banner 新增行）。

> 修订记录 v1→v1.1（2026-09-03，经用户生产实证授权）：C6 收窄。文档三源（中文官方 API 文档、英文官方 API 文档、CLI 元数据）一致称 SpotDuration 默认值 1，但本项目用户生产实证：未传该参数时实例频繁在 <1h 即因出价被平台回收——隐式默认在生产上未兑现保护期。故 AC-4 的显式 `--SpotDuration 1` 应视为**潜在行为修复**（强制启用文档承诺的保护），而非纯显式化；"默认 '1' 零语义变更"收窄为"文档语义等价，生产行为以 Rollout A/B 实证为准"。成因（RunInstances 路径未应用默认值 / 地域或时段差异 / 文档与实现不符）未能从可获取来源裁决，如实挂账。

# Intent Blueprint: Spot 出价倍率（price multiplier）与保护期（SpotDuration）参数化

## Background（评审发现）

`scripts/select_instance.py` 中 `spot_price_limit = total_price * 1.2` 是**固化魔法数字，且三处重复**：

| 位置                                      | 作用                                   | 状态                     |
| ----------------------------------------- | -------------------------------------- | ------------------------ |
| `scripts/select_instance.py:514`          | 主输出 `SPOT_PRICE_LIMIT`              | 活代码                   |
| `scripts/select_instance.py:534`          | `CANDIDATES_FILE` 每个重试候选行的限价 | 活代码                   |
| `scripts/create_spot_instance.py:207-217` | `calculate_spot_price_limit()` 内      | **死代码**（全仓无调用） |

风险：改一处漏另两处 → 主输出限价与重试时限价不一致；调用方（action 使用者）无法调节出价策略。相邻缺陷：两处活代码均用 `:.4f` 格式化，而 API 约束 `SpotPriceLimit` **最多 3 位小数**（见 S1），如产生 `0.8161` 类 4 位有效小数有被参数校验拒绝的风险（错误码 `InvalidSpotPriceLimit`，见 S1 错误码表；同表另见 `InvalidSpotPriceLimit.LowerThanPublicPrice`（S1 错误码表逐字摘录，2026-09-03 在线抓取："InvalidSpotPriceLimit.LowerThanPublicPrice The specified parameter \"spotPriceLimit\" can't be lower than current public price."）——出价低于当前公开价即拒；故 AC-1 对 0<m<1 的 Warning 仅是调用前提示，实际拦截分三层：本地 floor 守卫（AC-2，策略盲）、API 参数校验、API 出价低于公开价拒单（后两层在 RunInstances 时执行，层间独立，前者不蕴含后者）。

## Sources（一手来源摘录，各腿可直接复验）

- **S1 官方 RunInstances API 文档**（https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-runinstances ，本会话 2026-09-03 在线抓取，摘录原句）：
  - SpotDuration（参数表）: "The protection period of the spot instance, in **hours**. Valid values: **1**: After the instance is created, Alibaba Cloud guarantees that the instance will not be automatically released for 1 hour. After 1 hour, the system compares the bid price with the marketplace price in real-time and checks resource inventory to determine whether to retain or revoke the instance. **0**: ... does not guarantee a runtime... **Default value: 1**. Note This parameter currently supports **only the values 0 and 1**. **Spot instances are billed by second.** Select an appropriate protection period based on the execution duration of your tasks. Alibaba Cloud sends a notification through an ECS system event 5 minutes before the instance is revoked."
  - SpotPriceLimit（参数表）: "The maximum hourly price of the instance. This parameter supports up to **three decimal places** and takes effect when SpotStrategy is set to SpotWithPriceLimit."
  - SpotDuration 默认值（zh 现行源摘录，同 URL https://www.alibabacloud.com/help/zh/ecs/developer-reference/api-ecs-2014-05-26-runinstances ，2026-09-03 在线抓取）: "SpotDuration integer 否 抢占式实例的保留时长，单位为小时。取值： 1：创建后阿里云会保证实例运行 1 小时不会被自动释放……0：创建后，阿里云不保证实例运行时长……默认值：1。"
  - SpotStrategy（参数表，v2 增补摘录，zh 官方文档 https://www.alibabacloud.com/help/zh/ecs/developer-reference/api-ecs-2014-05-26-runinstances ，2026-09-03 在线抓取）: "SpotWithPriceLimit：设置上限价格的抢占式实例。SpotAsPriceGo：系统自动出价，跟随当前市场实际价格。"（zh 官方文档，2026-09-03 在线抓取）
  - 策略绑定对比（R4 异源发现闭环）：SpotPriceLimit 段落**显式**绑定 SpotWithPriceLimit；SpotDuration 段落**无任何策略绑定子句**（S1 全段在档，对比同表 SpotPriceLimit 的显式绑定）→ SpotDuration 为策略无关（SpotWithPriceLimit 与 SpotAsPriceGo 均适用）；SpotAsPriceGo 路径另由 Rollout 实证闭环。
- **S2a 本机 aliyun CLI 3.4.11 `RunInstances --help` 元数据**（与本仓库实际调用的 API 同一接口，直接相关）："The protection period of the spot instance. Unit: hours... Default value: 1."
- **S2b 同 CLI `CreateInstance --help` 元数据**（另一 API，仅作旁证，不背书 RunInstances）："...You can set this parameter only to 0 or 1."——RunInstances 侧的 0/1 约束由 S1 原句独立成立，不依赖 S2b。
- **S3 本地实证**（本会话，2026-09-03）：向 aliyun CLI（本机 3.4.11）传入不在其元数据中的伪参数 `--TotallyBogusParam 42`，CLI 不在本地做参数校验、直接进入客户端初始化（鉴权）阶段 → CLI 对未知参数不做本地拦截；但"参数被序列化进 RPC 且被服务端接受"未实证，action 固定的 CLI 3.2.2 兼容性由灰度验证闭环（见 Rollout）。
- **S4 仓库源码**：上述三处 1.2 的文件:行号；`action.yml` 的 select/create 两步 env 注入；README.md/README.cn.md 输入表。
- **S1b 官方 ModifyInstanceAutoReleaseTime API 文档**（https://www.alibabacloud.com/help/en/ecs/developer-reference/api-ecs-2014-05-26-modifyinstanceautoreleasetime ，2026-09-03 在线抓取）：定时自动释放对 spot 实例可用，原文 "Changes the automatic release time of a pay-as-you-go **or spot instance**"；同页另句原文 "The release time must be at least 30 minutes later than the current time."——AutoReleaseTime 明确支持 spot 实例；RunInstances 侧生效由本仓库 smoke-test.yml 的 "Verify AutoReleaseTime is set (defense line 3)" 步骤（经 DescribeInstances）对真实 spot 实例的生产实证背书；C7 补强范围仅限**窗口外共存**（本仓库默认 TTL 240min 落在任何 1h 窗口之外，AutoReleaseTime 与 spot 共存有生产实况支撑）；**窗口内触发**（TTL<60min）不受此补强覆盖——鉴于 C6（隐式默认未兑现保护，历史实例可能无 operative 保护窗口），窗口内腿仅为 S1b 引句推论，以 Rollout 45min spot-check 闭环。
- **S5 编排者在线复核**（2026-09-03，同源腿返回后）：S1 关键句逐句重取命中；S2a `Unit: hours` 复验存在；S1 错误码表含 `InvalidSpotPriceLimit` 与 `InvalidSpotPriceLimit.LowerThanPublicPrice`。
- **S6 历史 Snapshot（Wayback，原文 URL：http://web.archive.org/web/20230206024544/https://help.aliyun.com/document_detail/63440.html ，2026-09-03 编排者在线抓取）**：当时即已为小时制——"抢占式实例的保留时长，单位为小时。取值范围：0~~6。保留时长2~~6正在邀测中……取值为0，则为无保护期模式。默认值：1。"；同页 "支持最大3位小数"。现行 0/1 是从 0~6 收窄而来；早期"分钟级取值"的说法无一手来源支持，不采用。

## 核心主张清单（Core Claims — coverage-verified 锚点）

- C1【仓库，v1.3.0 评审时点快照——v1.4.0 已修复，见 Test Mapping 实施状态边界注】1.2 硬编码共三处：select_instance.py 两处活代码 + create_spot_instance.py `calculate_spot_price_limit()`（207-217 行）死代码（无调用方）。下表行号同为此快照。
- C2【S1】`SpotPriceLimit` 最多 3 位小数；当前 `:.4f` 有 4 位有效小数风险。
- C3【S1/S2a/S6】`SpotDuration` 单位为**小时**，仅接受 `0` 或 `1`，默认 `1`（现行 S1+S2a；历史 0~6 小时见 S6）。
- C4【S1】Spot 实例**按秒计费**；保护期内提前释放不按 1 小时整收（"Spot instances are billed by second"）。
- C5【S3，收窄】本机 aliyun CLI 3.4.11 实证：CLI 不在本地校验元数据外参数；参数是否透传至服务端未实证，action 固定的 CLI 3.2.2 兼容性待灰度验证（见 Rollout）。
- C6【S1+S2a，v1.1 收窄】现行 API 文档（zh/en/CLI 元数据三源一致）称未传 SpotDuration 时默认 1（1 小时保护）；但本项目用户生产实证：未传参时实例频繁 <1h 被出价回收——隐式默认在生产上未兑现保护（实证来源：用户口述报告，2026-09-03 会话授权，无可归档工件——标记为**不可复验的经验锚点**，A/B 项为其可审计化路径）。新参数默认 `"1"` 显式传递，应视为对观察问题的修复而非零行为变更；文档等价性与生产行为的差异成因未决，Rollout 含 A/B 验证项。
- C7【S1+S1b】保护期防的是**系统回收**（出价/库存比对）；用户侧释放路径（cleanup / AutoReleaseTime / 自毁）不受影响。S1 原句覆盖系统回收语义；S1b 证明 AutoReleaseTime 对 spot 实例可用（最短 30min）；"TTL<60min 时 AutoReleaseTime 在保护窗口内照常触发"为基于 S1b+仓库生产实况的推论，Rollout 含对应 spot-check。

## Core Use Cases

- UC-1: action 调用者可通过 `spot_price_multiplier` 输入指定出价倍率（默认 1.2，保持现状），倍率同时作用于主输出与全部重试候选。
- UC-2: action 调用者可通过 `spot_duration` 输入指定保护期（默认 "1" = 1 小时防系统回收，等于 API 现行默认；"0" = 无保护期，随时可被系统回收、任务中断风险更高），仅接受 0/1。计费与保护期选择无关（按秒计费，见 C4），不暗示任何价格差异。
- UC-3: 非法取值响亮失败（error_exit 非零退出 + 解释性错误信息），绝不静默钳制。
- UC-4（v2）: action 调用者可通过 `spot_strategy` 输入显式选择自动出价 `SpotAsPriceGo`（系统自动出价、随行就市）；显式设置后倍率与限价**不参与竞价**（RunInstances 命令不带 --SpotPriceLimit；输入仍全量校验，见设计决策），实例选型/可用区/VSwitch/重试机制照常。默认 `SpotWithPriceLimit`（有限价时保持 v1.4.0 行为；无限价时差异见 AC-8 (c)）。

## 设计决策（显式声明，防误改）

- **倍率在 select_instance 计算，create_spot_instance 保持纯消费**：价格数据在 select 侧，candidates 文件携带预计算限价；倍率 env 只需注入 select 步。`create_spot_instance.py` 的死代码 `calculate_spot_price_limit()` 直接删除（消灭第三处 1.2，而非参数化死代码）。
- **默认值与 API 文档语义等价（v1.1 收窄传播）**：`spot_price_multiplier` 默认 `"1.2"`；`spot_duration` 默认 `"1"`——与 API 文档默认**语义等价**；生产行为差异（隐式默认未兑现保护）未决，以 Rollout A/B 实证为准（见 C6）。
- **校验语义（复合模式，round-1 修正归因）**：空串回退默认沿用 `select_instance.py` 的 `MIN_CPU`/`MAX_CPU` 模式（`os.environ.get(...).strip()` + `if str else default`）；非数值/非法域响亮失败沿用 `create_spot_instance.py` 的 `load_ttl_minutes()` 模式（error_exit）。注意：`load_ttl_minutes` 本身对空串是**响亮失败**而非回退默认，不得照抄其取默认值形状。
- **倍率 <1 只警告不阻断**：出价低于市价可能导致创建失败或更快被回收，属合法的风险选择。
- **v2 策略只在 create 侧消费（显式决策）**：`SPOT_STRATEGY` 仅注入 create 步；select_instance.py 零改动——advisor 价格仍用于选型排序与 candidates 文件格式稳定（限价列照写，SpotAsPriceGo 下 create 忽略之）。“倍率无效”语义 = 不影响出价；**倍率校验保留**（无效输入在自动出价下也响亮失败——配置腐烂早暴露，非遗漏）。
- **v2 策略三分支（含可达性披露，R2 修正）**：env `SPOT_STRATEGY` 缺省或空串 → 保留 v1.4.0 回退（有限价→SpotWithPriceLimit，无→SpotAsPriceGo）。可达性：经 action **省略**输入时 default "SpotWithPriceLimit" 生效（恒非空）；但 GitHub Actions 语义下调用方**显式传空串** `spot_strategy: ''` 会覆盖 default 并以空串注入 env → 落入回退分支——与省略输入在空限价角语义不同（省略=显式 WPL→error_exit；空串=None→静默 ASG），该差异为已知行为并披露，不构成"绝不静默切换"的违反（空串=调用方主动未表达选择）。直跑脚本不设 env 同样落入回退分支。显式 `SpotAsPriceGo`（大小写不敏感规范化）→ 一律 SpotAsPriceGo 且不发 --SpotPriceLimit（优先于倍率）；显式 `SpotWithPriceLimit` → 若**该次创建所用限价来源为空**（重试路径=当前候选行第 4 列；单次路径=SPOT_PRICE_LIMIT env）→ error_exit 响亮失败，绝不静默切换策略。
- **v2 校验**：`load_spot_strategy()` 大小写不敏感匹配两个合法值并规范化为规范枚举名；非法值 error_exit 且错误信息列出全部合法值；不得 type: boolean。
- **`:.4f` → `:.3f`**：对齐 C2 的 API 约束（同批顺手修复，因恰好改同一行）。
- **README 双语同步**（`.cursor/rules/04-readme-sync.mdc` alwaysApply）：注明按秒计费、SpotDuration=1 ≠ 最低消费 1 小时。

## Acceptance Criteria (BDD)

- AC-1: `select_instance.py` 新增 `load_price_multiplier()`：env `SPOT_PRICE_MULTIPLIER` 缺省/空串 → 1.2；非数值、≤0 或**非有限值（nan/inf，`math.isfinite` 必须通过）** → error_exit（退出码 1）；0<m<1 → stderr Warning（例外：若任一作用点限价将归零，AC-2 floor error_exit 优先，见 AC-2）。倍率同时作用于主输出 `SPOT_PRICE_LIMIT` 与 `CANDIDATES_FILE` 每行限价（两处不得再各自硬编码）。
- AC-2: `SPOT_PRICE_LIMIT`、candidates 文件行中限价、及 stderr 调试两行（Total price / Spot price limit）统一格式化为 `:.3f`（≤3 位小数，对齐 API 约束）。若**任一作用点**（主输出或某候选行）计算限价 < 0.0005（格式化将归零为 "0.000"）→ error_exit 响亮失败，绝不发送 0 限价。floor 守卫位于 select 步且**策略盲：SpotAsPriceGo 下同样无条件生效**（属"全量校验"语义的刻意设计——即使限价将被竞价忽略，也不允许畸形值通过流水线）。
- AC-3: `create_spot_instance.py` 新增 `load_spot_duration()`：env `SPOT_DURATION` 缺省/空串 → 1；必须可解析为 int 且 ∈{0,1}，否则 error_exit 且错误信息包含 "hours" 与 "only 0 or 1"（不提及分钟制历史——见 S6，无一手来源）。
- AC-4: `create_instance()` 增加 `spot_duration: int | None = None` 参数：非 None 时向 RunInstances 命令追加 `--SpotDuration <n>`；None 时不追加。`main()` 两条创建路径（候选重试 + 单次）均传入校验后的值；启动 banner 打印 `Spot Duration: N hour(s)`。
- AC-5: 删除 `create_spot_instance.py` 中无调用方的 `calculate_spot_price_limit()`，模块内不得残留对它的引用。
- AC-6: `action.yml` 声明输入 `spot_price_multiplier`（default `"1.2"`）与 `spot_duration`（default `"1"`），两者均为**裸字符串输入，不得声明 `type: boolean`**（GitHub 对 boolean 输入会把 "0"/空串强转 false，破坏 int 解析）；select-instance 步 env 注入 `SPOT_PRICE_MULTIPLIER`，create-instance 步 env 注入 `SPOT_DURATION`。
- AC-7: README.md 与 README.cn.md 输入表同步新增两行（描述含按秒计费语义），CHANGELOG.md 增加条目。（文档无自动化测试，如实标注：人工核对）
- AC-8: 向后兼容（语义层，v1.1 收窄传播）：不设置新 env 时，出价策略与保护期与 API 文档默认**语义等价**（倍率 1.2；SpotDuration 显式 "1" == 文档默认——生产行为差异见 C6，以 Rollout A/B 实证为准）。**四处有意差异明确枚举、不构成向后兼容违反**：(a) 限价格式 .4f → .3f（AC-2）；(b) RunInstances 命令新增 --SpotDuration 1（AC-4）；(c) v2：显式/默认 SpotWithPriceLimit 且该次限价来源为空 → error_exit（v1.4.0 为静默回退 SpotAsPriceGo）；(d) v2：banner 新增 Spot Strategy 行。其中 (a)(b) 相对原现状（v1 层），(c)(d) 相对 v1.4.0（v2 层）。test_defaults_preserve_current_behavior 断言语义默认值（multiplier=1.2、duration=1），不得断言 .4f 快照。
- AC-9（v2）: action.yml 声明输入 `spot_strategy`（裸字符串，禁 type: boolean，default `"SpotWithPriceLimit"`，描述注明：SpotAsPriceGo 下倍率与限价不影响出价（命令不带 --SpotPriceLimit），但输入仍全量校验）；create-instance 步 env 注入 `SPOT_STRATEGY`；select 步不注入（select 零改动）。
- AC-10（v2）: `create_spot_instance.py` 新增 `load_spot_strategy()`：env `SPOT_STRATEGY` 缺省/空串 → None（保留旧回退：有限价→SpotWithPriceLimit，无→SpotAsPriceGo）；非空则大小写不敏感匹配并规范化为 `SpotWithPriceLimit`/`SpotAsPriceGo`；非法值 error_exit 且错误信息列出两个合法值。
- AC-11（v2）: 两条创建路径（候选重试 + 单次）：显式 `SpotAsPriceGo` → 命令含 `--SpotStrategy SpotAsPriceGo` 且**不含** `--SpotPriceLimit`（忽略该次创建的限价来源）；显式 `SpotWithPriceLimit` 且该次限价来源为空（重试路径=当前候选行第 4 列，单次路径=SPOT_PRICE_LIMIT env）→ error_exit（不静默切换）；显式 `SpotWithPriceLimit` 且有限价 → 双旗标齐备（--SpotStrategy SpotWithPriceLimit + --SpotPriceLimit）；未设置（空）→ 策略/限价旗标**语义**与 v1.4.0 一致（回归，字节级差异见 AC-8 (d)）。banner 新增 `Spot Strategy: X` 行：显式时 X=枚举名（SpotWithPriceLimit/SpotAsPriceGo）；未设时 X=字面值 `auto`（解析规则见用例粒度注——非打印文本）；SpotAsPriceGo 下不打印 Spot Price Limit 行。
- AC-12（v2）: README.md 与 README.cn.md 输入表同步新增 spot_strategy 行（描述含"SpotAsPriceGo 下倍率/限价不影响出价但输入仍全量校验"与优先级语义），CHANGELOG 增条目。（文档，人工核对——如实标注）

## Non-Functional Requirements

- NFR-1: 不新增依赖（仅标准库 + 既有 dev 工具链）。
- NFR-2: `ruff check` 与 `ruff format --check` 干净；`pytest -q` 全绿；测试零网络零凭证。
- NFR-3: env 解析与校验为纯函数或可 monkeypatch 的 loader（沿用 `load_ttl_minutes` 的可测形状），不内联散落。
- NFR-4: README.md/README.cn.md 内容同步（双语规则）。

## Non-Goals

- 不支持 NoSpot（本 action 定位 spot runner；非 spot 为另一产品形态）。
- SpotAsPriceGo 下不改变选型逻辑：advisor 价格仍用于实例类型排序与 candidates 文件格式（限价列照写，仅竞价时忽略）。
- 不在 SpotAsPriceGo 下跳过倍率校验（显式决策：所有声明输入一律校验，见设计决策）。
- （v1.1→v2 收窄）不切换 Spot 策略的原 v1 条款仅适用于**缺省路径**：未设 SPOT_STRATEGY 时既有回退逻辑不动；显式输入的三分支行为见 v2 设计决策与 AC-11。

- 不实现 >1 小时保护期（历史版本曾允许 0~6 小时邀测，现行仅 0/1，见 S1/S6）。
- 不修改 TTL/AutoReleaseTime 语义（用户侧释放路径不受保护期影响）。
- 不做真实账单核验（记入 rollout 人工 spot-check：一次 <1h 提前释放的账单应按秒计）。

## Acceptance-Criteria -> Test Mapping（RED 阶段冻结）

注：实施状态边界（2026-09-03 更新，R2 修正）——AC-1..AC-8 的 **v1 层部分**（含 (a)(b) 差异与全部 v1 映射测试）已在 v1.4.0（tag 2026-09-03 15:51）落地交付；**AC-8(c)(d) 与 AC-9..AC-12 为 v2 待实施**（(c)(d) 的行为断言由 AC-11 映射测试锚定，防止 RED 收集器遗漏）。下述映射中 AC-1..AC-8 行为已交付事实的回归锚，AC-9..AC-12 行为 RED 冻结目标。`tests/test_select_instance.py` 于 v1.4.0 已建（历史注：v1 RED 阶段时为新建）。

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
- AC-10 → tests/test_create_spot_instance.py::test_load_spot_strategy_validation
- AC-11 → tests/test_create_spot_instance.py::test_spot_as_price_go_overrides_price_limit
- AC-11 → tests/test_create_spot_instance.py::test_explicit_price_limit_without_limit_fails_loudly
- AC-11 → tests/test_create_spot_instance.py::test_default_strategy_fallback_unchanged
- AC-9 → tests/test_action_workflow.py::test_spot_strategy_input_and_env_wiring

用例粒度注（非映射行）：

- test_price_multiplier_invalid_fails_loudly 内含 nan/inf 用例。
- test_price_multiplier_default_and_custom 内含 0<m<1 用例（SPOT_PRICE_MULTIPLIER='0.5' → exit 0、stderr 含 Warning）。
- AC-2 floor 检查作用点 = **两处**：主输出与每个候选行（任一计算限价 < 0.0005 均 error_exit）；test_spot_price_limit_below_rounding_floor_fails_loudly 参数化两个作用点。
- test_spot_price_limit_formatted_to_three_decimals 同时断言 stdout（SPOT_PRICE_LIMIT= 行与 candidates 文件行）与 stderr 调试两行（`Total price: X.XXX`、`Spot price limit: X.XXX`）均为 3 位小数（capsys 双流捕获）。
- test_run_instances_command_includes_spot_duration 参数化两分支（传入 0/1 → 命令含 --SpotDuration；传 None → 命令不含，None 分支另由既有 test_run_instances_command_includes_auto_release_time 的默认调用隐式覆盖）。
- AC-4 双调用点钉扎（**两者都要**，不用或；(a)(b) 均置于 test_run_instances_command_includes_spot_duration 内）：(a) 静态断言 create_spot_instance.py 源码中 create_instance( 的两个调用点均含 spot_duration 实参；(b) 新建 CANDIDATES_FILE fixture 驱动 main() 重试路径——fixture 形状：tmp_path 下写 3 行候选文件（`类型|可用区|vsw-xxx|0.1234|8` 格式），设 env CANDIDATES_FILE=<path> + 必需 env（密钥/区域/VPC/SG/INSTANCE_NAME 等），monkeypatch subprocess.run 捕获 argv，断言重试路径发出的命令含 --SpotDuration。
- test_spot_duration_defaults_to_one_without_env 覆盖单次路径：不设 CANDIDATES_FILE、设必需 env（同重试 fixture 另加 INSTANCE_TYPE、ALIYUN_VSWITCH_ID 及 ALIYUN_IMAGE_ID 或 ALIYUN_IMAGE_FAMILY 之一）、monkeypatch subprocess.run 后驱动 main()，断言 --SpotDuration 1 出现在单次路径命令中且 banner 含 `Spot Duration: 1 hour(s)`。

Coverage Notes：AC-7 与 AC-12（README/CHANGELOG 文档同步）无自动化测试，人工核对——不占映射行（映射值必须是收集器可枚举的测试名）。AC 形态采用祈使句规格式（与本仓库 forensics 蓝图一致的家族惯例），Given/When/Then 三段式豁免，可测性不受影响。

v2 用例粒度注（非映射行）：test_spot_as_price_go_overrides_price_limit 参数化两条路径（CANDIDATES_FILE fixture 重试路径 + 无 CANDIDATES_FILE 单次路径），均断言含 `--SpotStrategy SpotAsPriceGo` 且不含 `--SpotPriceLimit`（尽管 candidates 行/env 里有限价）；test_explicit_price_limit_without_limit_fails_loudly 内含显式 WPL+有限价的 happy-path 断言（双旗标齐备：--SpotStrategy SpotWithPriceLimit + --SpotPriceLimit，即经 action 默认输入的最主路径）；test_default_strategy_fallback_unchanged 断言未设 SPOT_STRATEGY 时：有限价 → SpotWithPriceLimit+限价，无限价 → SpotAsPriceGo（v1.4.0 语义回归）；test_load_spot_strategy_validation 含大小写规范化用例（'spotaspricego' → SpotAsPriceGo）；banner 断言归属映射测试：`test_spot_as_price_go_overrides_price_limit` 承载 ASG 分支 banner（打印枚举名 SpotAsPriceGo 且不打印 Spot Price Limit 行）；`test_explicit_price_limit_without_limit_fails_loudly` 承载显式 WPL 分支 banner（打印枚举名 SpotWithPriceLimit）；`test_default_strategy_fallback_unchanged` 承载未设分支 banner（打印字面值 `auto`，banner 仅此两词形态，不含任何中文括注；解析规则——重试路径逐候选行、单次路径看 SPOT_PRICE_LIMIT env——属解释说明，不进 banner）；新用例注释继续用 `spot-bid AC-N` 命名空间（注意与 test_create_spot_instance.py 头部 TTL 蓝图裸 AC-9/AC-10 及 test_action_workflow.py 裸 AC-11 注释区分）。

## Rollout 验证（实施后）

- 默认参数组合与 API 文档默认**语义等价**（出价策略 = 1.2×市价；保护期 = 1h）；生产行为差异（隐式默认未兑现保护）以 A/B 项实证为准；字节级差异以 AC-8 (a)-(d) 枚举为准。回归测试断言语义同一（loader 默认值 + argv 旗标集合语义），不做字节相等断言。
- 灰度（定义：在可传入非默认 action 输入的调用方 workflow 触发一次真实创建——本仓库 `.github/workflows/smoke-test.yml` 加输入或一次性测试仓库均可）：跑 `spot_duration: 0` + `spot_price_multiplier: 1.5`，核对 banner `Spot Duration: ...` 与实例侧 SpotDuration 生效值（经 DescribeInstances/DescribeInstanceAttribute 核对，具体响应字段以实测为准——smoke-test.yml 已有 DescribeInstances 使用先例）（**闭环 C5**：验证 CLI 3.2.2 确实透传 `--SpotDuration` 并被服务端接受）；一次 <1h 任务提前释放后核对账单按秒计（C4 spot-check）。
- 另跑一次显式 `spot_strategy: SpotAsPriceGo`（v2 语义，经 action：默认倍率照常计算、限价在场但被忽略）+ `spot_duration: 1`：断言实际执行的 RunInstances 命令**不含 --SpotPriceLimit** 且含 --SpotDuration 1，并确认服务端接受（闭环 R4-D1 策略无关性 + v2 优先级语义端到端）。
- A/B 验证隐式默认行为（**v1.1 新增，闭环 C6 差异成因**）：同区域同规格分别以 v1.3.0（不传 SpotDuration）与 v1.4.0（显式 `--SpotDuration 1`）各创建若干实例，在市价波动窗口对比 <1h 出价中断率；并经 DescribeInstances/DescribeInstanceAttribute 核对 v1.4.0 实例保护生效。若 v1.3.0 对照组同样无中断，则差异成因更可能为时段/地域性，记录归档。
- 另跑一次 `instance_ttl_minutes: 45` + `spot_duration: 1`：核对 AutoReleaseTime 在 1 小时保护窗口内到点照常释放（**闭环 C7 残余推论**）。
