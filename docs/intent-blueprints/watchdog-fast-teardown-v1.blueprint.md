---
blueprint_version: v1.2
frozen_at: 2026-09-18
revised_at: 2026-09-18
task: 成功路径快速回收——ephemeral runner 完成即跳出停止判定窗（ACTIONS_RUNNER_HOOK_JOB_COMPLETED 标志 + watchdog 短路）
status: frozen
---

# Intent Blueprint — 成功路径快速回收（fast teardown）

This blueprint is the FROZEN, read-only anchor for the convergence loop. The Coder cannot edit it. Reviewer must diff every change against it. To change intent, use the Blueprint Revision Channel (status -> revising -> Planner+human -> version bump -> re-freeze). See references/intent-blueprint.md.

> 修订记录 v1→v1.1（2026-09-18，经用户授权；plan-reviewer 外环 round-1 对 v1 判 inconclusive——工件当时未物化，其可执行半面（集成点核证）+ 三条 findings 据此吸收）：①**补记 Always() 语义**（fetched JobExtension.cs:570-580：钩子注册为 PostJob 步、`condition: Always()`）——钩子在成功/失败/取消三类终态都执行，标志落于全部终态路径。②**新决策 6：失败路径取证竞态门控**——快拆 ~15-20s 会反转 watchdog-hardening v1.2 :37 记录的 fetch(最坏 ≈40s)-vs-自毁(≈130s) 竞态，失败/取消路径的 console 取证会被饿死；裁决为成功/失败路径分离 + 机制实现期裁定。③**FAST_TEARDOWN_CONFIRMATIONS 降为常量**（YAGNI：无代理质量类运营场景支撑旋钮）。④**修订义务登记**：本蓝图落地时，watchdog-hardening v1.2 :37 竞态算术与 pr2-intervention :55/:104 Rollout 基线（≈130-135s）经修订通道加 superseded-by 注。⑤**反欺骗前提修正**：/run root-only 不构成防 job 代码伪造标志的论据（本舰队 job 即 root）——标志仅承担「job 已终态」一手信号，不承担反欺骗。

> 修订记录 v1.1→v1.2（2026-09-18，经用户授权；plan-reviewer round-2 定向 rewrite——五处修订卫生，设计核与 round-1 闭合均确认 sound）：①决策 2/NFR-3 与决策 7 的常量裁决对齐（废除 FAST_TEARDOWN_CONFIRMATIONS 的 /etc/environment 覆盖通道；杂散键惰性）。②AC-2 阈值随门控裁定条件化（A=1；B=⌈45/5⌉=9）。③UC-1 随门控分叉。④"~3 倍"算术修正为 ~2.4 倍（55-60s vs ≈130s）。⑤候选 A 判读保守方向入 AC-2b（仅结论性成功证据落标志；不确定 ⇒ 不落 ⇒ 全确认窗）。⑥45s 地板引用 fetch 旋钮缺省值来源（connect 10s + read 30s + 0 重试，fetch-console-output.sh:66-73——旋钮被 env 覆盖时地板随之失据，属运营边界）。

## 背景

v1.6.0 落定后，watchdog 停止判定窗为「最长连续不活跃确认窗」（pr2-intervention 决策 1：三态活探测、窗内任一 active 清零跳出；缺省 24×5s=2min，`watchdog_stop_window_seconds` 可调）。已知残留：**成功路径烧满窗口**——`--ephemeral` runner（user-data.sh `--ephemeral` 旗标）完成唯一天职后退出、永不回来，但「永久退出」与「自更新中途暂停」在 systemctl 探测层不可区分，watchdog 必须等满确认窗才能自毁（teardown ≈130-135s，README 已注明该语义限制）。

判别器的正确信号源仓库自己已经找到过：watchdog-hardening 蓝图背景记录了**正确的**钩子变量是 `ACTIONS_RUNNER_HOOK_JOB_COMPLETED`（当初删除的死配置用的是错误名 `ACTIONS_RUNNER_HOOK_POST_JOB`，全库 0 命中）。runner 在 job 完成时执行该钩子脚本——这是「job 确已完结」的一手证据，探测层不可区分性的根源由此消除。

本蓝图冻结其利用方式。**未实施**——实施时机由维护者排期（关联 v1.6.0 收尾挂账）。

## Sources

- S1: docs/intent-blueprints/watchdog-hardening-v1.blueprint.md（v1.2；钩子变量正名记录 + 「移除而非激活」决策的三条反对理由）
- S2: docs/intent-blueprints/pr2-intervention-v1.blueprint.md（决策 1 的语义限制条款；AC-5 的 /etc/environment 传递链模式）
- S3: actions/runner src/Runner.Listener/Runner.cs（fetched 2026-09-18：`--ephemeral` "Configure the runner to only take one job and then let the service un-configure the runner after the job finishes"）
- S4: templates/user-data.sh 现行 watchdog heredoc（三态探测 + 确认计数结构）

## Core Use Cases

- UC-1: ephemeral runner 完成 job 后，实例在门控裁定的快拆窗内进入自毁（A：≤2 次确认 ≈15-20s；B：45s 地板 ≈55-60s），而非烧满缺省窗 ≈130s
- UC-2: 自更新/重启/瞬态停止场景的行为**零变化**——仍走完整确认窗（假阳性防护不降级）
- UC-3: 钩子执行不阻塞 runner 自身关机路径（无同步自毁、无删除竞态）

## 设计决策（显式声明，防误改）

1. **标志文件而非同步动作**：钩子脚本仅 `touch /run/runner-job-completed`（+ 幂等）。绝不 in-hook 自毁——这恰好绕开 watchdog-hardening「移除而非激活 hook」决策的全部反对理由（阻塞 "Complete runner" 步骤、与 runner 自身关机→watchdog 形成删除竞态、零防御增量）。自毁仍由 watchdog 异步执行，dead-man switch 的本地约束不变。
2. **短路只缩不放**：watchdog 在 confirmed-inactive 计数起点检查标志——标志存在 → 确认阈值取快拆常量（成功门控 A=1；地板门控 B=⌈45/5⌉=9——见决策 7：常量，无覆盖通道，/etc/environment 杂散同名键惰性）；标志不存在 → 阈值不变（24/用户窗）。任何 active 探测照旧清零。**未知探测态不消费标志**（标志不改变 unknown 语义）。
3. **取证完整**：标志的落盘时间戳进 pre-destroy 取证转储（`stat -c %y` 一行）——「为什么这次 1 次确认就自毁」在日志里可答。
4. **钩子部署次序**：hook 脚本在 `svc.sh start` **之前**落盘并导出 env（沿既有 `.env` 写入模式）——job 可能在服务启动后任意时刻完成，晚于服务启动的钩子部署会漏首个 job。
5. **非 ephemeral 场景安全**：标志只在「job 完成」时写；常驻 runner 完成一个 job 后服务仍 active（探测即清零路径），标志残留在下次真实停止时短路——**可接受**（常驻 runner 的停止本就罕见且通常为运维意图），但需在 AC-4 测试中显式钉扎该语义选择。
6. **失败路径取证竞态（结果门控）**：钩子 `Always()` 触发 ⇒ 失败/取消路径同样落标志，而 action 侧清理正在这些路径做 console 取证（fetch 最坏 ≈40s；v1.2 :37 的竞态算术建立在 ≈130s 自毁之上）。无门控的 ~15-20s 快拆先于 fetch 杀实例——失败取证被饿死，不可接受。裁决：**成功终态快、失败/取消终态不快于 fetch 最坏界**。门控机制实现期裁定：候选 A——钩子从 runner 诊断产物（_diag 日志/结果通道）判读 job 结论后条件落标志；候选 B（无干净机制时回退）——无条件落标志，快拆确认地板取常量 45s（> fetch 最坏 40s；全路径生效，收益 ~2.4 倍（55-60s vs ≈130s；地板窗引用 fetch 旋钮缺省——connect 10s + read 30s + 0 重试，旋钮被 env 覆盖时此界随之失据）。
7. **FAST_TEARDOWN_CONFIRMATIONS 为常量非旋钮**：stop-window input 有代理质量场景支撑，快拆阈值无对应场景（外环 YAGNI 裁决）；成功路径常量 1，地板回退时常量 45s。

## Acceptance Criteria (BDD)

- AC-1: Given user-data bootstrap When 服务启动前 Then ACTIONS_RUNNER_HOOK_JOB_COMPLETED 指向已落盘的可执行钩子脚本，脚本体=幂等 touch 标志文件，无任何自毁/网络调用 — seam: `templates/user-data.sh` 渲染文本 (catches: 钩子存在性与非阻塞形状; misses: runner 是否真调用——外部行为，Rollout 验证)
- AC-2: Given 成功终态标志存在 When Phase-2 探测 confirmed-inactive Then 阈值取门控裁定的快拆常数（A=1；B=⌈45/5⌉=9）；Given 标志不存在 Then 阈值与现行 STOP_CONFIRMATIONS_REQUIRED 完全一致 — seam: watchdog heredoc 文本 (catches: 分支逻辑形状; misses: 运行时时序)
- AC-2b: Given 失败/取消终态 Then 快拆不快于取证最坏界（门控机制按决策 6 裁定形态落档：A=条件落标志的判读形状，**判读必须保守——仅结论性成功证据落标志，不确定/判读失败 ⇒ 不落 ⇒ 退化全确认窗**；B=45s 地板常量形状）——失败路径 console 取证不得被 watchdog 饿死 — seam: 渲染文本（门控形状）+ Rollout 时序实测 (catches: 门控存在性; misses: 真实 40s fetch——Rollout 补)
- AC-3: Given 任一 active 探测 Then 计数清零（标志不改变 reset 语义）；Given unknown 探测 Then 不递增不清零且不消费标志 — seam: watchdog heredoc 文本 (catches: 三态语义保持; misses: 无)
- AC-4: Given 常驻（非 ephemeral）runner 完成 job 后服务仍 active Then 后续真实停止走短路——该语义作为显式决策被测试钉扎（注释引用设计决策 5） — seam: 渲染文本 + 测试名 (catches: 语义选择的可审计性; misses: 运行时)
- AC-5: 自毁前取证转储含标志文件的 mtime 行 — seam: 渲染文本 (catches: 取证可答性; misses: 无)
- AC-6: 结构测试全套落档（下述映射），既有测试零回归 — seam: `tests/` 收集集 (catches: 存在性与零回归; misses: 语义强度——外环)

## Non-Functional Requirements (NFR)

- NFR-1: dead-man switch 本地约束不变：钩子与短路逻辑零网络依赖；标志文件在 tmpfs（/run）随实例消亡。
- NFR-2: 无「删测试保绿」；既有 24/窗口语义测试不得削弱。
- NFR-3: 常量语义：快拆阈值无键无读取器；/etc/environment 中杂散同名键惰性（与 STOP_CONFIRMATIONS_REQUIRED 的 AC-9 覆盖通道无关）。

## Acceptance-Criteria -> Test Mapping

（RED 阶段填入；本蓝图未实施，映射留空为合法状态——实施时必须先落映射再写实现）

## Rollout 验证（实施后）

- smoke-test happy 腿（成功终态）：从 "runner 完成" 到 "实例销毁" 的耗时按门控结局二分——门控 A：≈15-20s（1 次确认 + 10s 自毁等待）；门控 B：≈55-60s（45s 地板 + 10s）。这是本蓝图收益的直接度量。
- smoke-test failure 腿（失败终态）：console 取证 artifact 必须完整上传（fetch 完成先于实例消失）——竞态反转的负验证。
- failure 腿（bootstrap 失败，无标志）：行为与现状逐字节一致。
- 取证演练：dump 中出现 job-completed mtime 行。

## 范围外（显式）

- BOOTSTRAP_WATCH_TIMEOUT input 化（issue #12）。
- 非 ephemeral 常驻 runner 的调度策略。
