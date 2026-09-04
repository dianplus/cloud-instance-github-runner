---
source: workspace/cross-source-review/runs/20260903-222855-watchdog-review-verify/artifact.md（"watchdog 误杀分析裁决复核"工件，本文由其改编落档）
csr_convergence: substantive_converged —— 同源+异源两轮复核各 11 项发现、0 blocker、两轮均 pass（收敛记录：workspace/cross-source-review/runs/20260903-222855-watchdog-review-verify/convergence-record.json）；rightness 轴归人：本文收敛的是候选集与排除算术，不裁决事故真实成因（见 §8）
date: 2026-09-03
---

# Incident Review: job 运行中 runner 实例销毁（v1.4.0，job 报 cancel）

- 日期: 2026-09-03
- 状态: 复核收敛（候选集闭合）；修复由 watchdog-hardening-v1 蓝图承接（见 §9）
- 影响: v1.4.0 双腿矩阵运行中实例被销毁——x86 腿死于创建后 14min、aarch64 腿死于 15min，job 报 cancel
- 严重度: 待定案（成因候选集已收敛至窄集，单因未定——取证数据随实例蒸发，见 §6）

## 1. 概要

第三方分析认定"action 自带 runner watchdog 在重载下命中瞬态非 active → 误杀实例"。第一方（编排者）对该分析做了逐条裁决（V1/T1 … V5/T5，含 4a/4b/4c 子项合计七项）；随后经同源+异源两轮 csr 复核收敛。复核的物质性产出有三：

1. **排除算术收窄候选集**：对三个界（watchdog Phase-1 1800s、action 侧 120s 等待、AutoReleaseTime ≥30min 下限）各做一次不可达推导后，剩余候选为：上游取消→watchdog（by-design）/ watchdog 误杀（查询失败型或瞬态）/ OOM→真实停止 / spot 回收仅当 1 小时保证不兑现（§3-§4）。
2. **关键实证 C-PH-INERT**：user-data.sh 设置的 `ACTIONS_RUNNER_HOOK_POST_JOB` 不被 actions/runner 读取——post-job 自毁路径自 initial commit 起是失效的死配置，"watchdog=异常兜底、post-job=正常路径"的原二分法不成立（§5）。
3. **修复决策**：采纳方案 A（连续确认 + 查询失败分流）与方案 D（自毁前取证武装），否决 B/C（§7）。

背景事实：v1.2.1↔v1.4.0 的 watchdog 逻辑零变更（编排者会话内字节级 `git diff v1.2.1 v1.4.0 -- templates/user-data.sh`：探测/轮询/超时相关行 0 增删）——本次非 v1.4.0 回归。

## 2. 复核过程与来源

- **S1 actions/runner ADR 1751-runner-job-hooks.md**（编排者 2026-09-03 在线取证逐字归档）：官方钩子变量为 `ACTIONS_RUNNER_HOOK_JOB_STARTED` / `ACTIONS_RUNNER_HOOK_JOB_COMPLETED`；钩子 `always()` 在变量设置时执行、以 Runner 用户身份。
- **S2 actions/runner 代码检索**（同日，编排者在线取证存档；异源腿对三个正向命中文件做了文件级佐证）：`ACTIONS_RUNNER_HOOK_POST_JOB` 全库 **0 命中**；`ACTIONS_RUNNER_HOOK_JOB_COMPLETED` 3 命中（ADR 1751、src/Runner.Worker/JobExtension.cs、src/Test/L0/Worker/JobExtensionL0.cs）。
- **S3 spot 回收语义**（阿里云官方文档截句）：创建后 1 小时保证不自动释放（"guarantees that the instance will not be automatically released for 1 hour"）+ 回收前 5 分钟经 ECS 系统事件发送预警。
- **S4 systemd 状态语义**：一手手册抓取失败——凡涉 systemd 状态机的主张按"推理假说"对称标注，不冒充有源（§8）。

## 3. 事故候选集（裁决后）

| #   | 候选                             | 机制                                                                                                                                                                                              | 裁决状态                                                                                                         |
| --- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 1   | 上游取消 → watchdog（by-design） | ephemeral runner 单 job 结束（cancelled 亦为结束）→ 服务真实停止 → watchdog 自毁                                                                                                                  | 成立的 by-design 链；此时 watchdog 行为正确                                                                      |
| 2   | watchdog 误杀·查询失败型         | 重载下 `systemctl list-units` 查询失败/超时返回空，探测函数 `2>/dev/null` 吞错 → 空 ≡ 非 active → **单次命中即自毁**（`while runner_service_active; do sleep 5; done` 后直接 exec self-destruct） | 与代码形状直接耦合的最真实候选（推理假说，无实例端日志实证）                                                     |
| 3   | watchdog 误杀·瞬态状态抖动       | systemd 瞬态 deactivating 被探测误读为非 active                                                                                                                                                   | 机制不成立/未证：抖动主张与第一方机制反驳**双方均为无源推理假说**（S4 缺失，对称标注）                           |
| 4   | OOM → 真实停止                   | 重载 OOM killer 杀 runner 主进程 → 服务真实停止 → watchdog 正常触发                                                                                                                               | 与误杀的日志表现不可区分；待 journal OOM 记录裁决                                                                |
| 5   | spot 回收                        | 价格回收/库存回收                                                                                                                                                                                 | **仅当 1 小时保证不兑现**才可达——高度可能排除（§4 软排除）                                                       |
| 6   | action 侧销毁链                  | "Cleanup on Failure" 步 `if: failure() \|\| cancelled()` → cleanup-instance.sh → DeleteInstance --Force                                                                                           | 对本次事故大概率不可达（§4 界 2）；作为通用时序候选保留（fail-fast 取消兄弟 setup job 的变体需调用方工作流核查） |
| 7   | AutoReleaseTime 云侧定时销毁     | --AutoReleaseTime 到期强制释放                                                                                                                                                                    | 不可达（§4 界 3）                                                                                                |

修正说明（据 C-PH-INERT，§5）：修正后**实例内**自毁链只剩 watchdog 一条——原以为并存的 post-job hook 路径从未生效；action 侧另有上表 #6 一条 GitHub 侧销毁链。

## 4. 排除算术

> 锚点披露：本节时间戳均系第三方分析转述、未经独立核实（x86 创建锚 10:58:38 = CreateInstance success）；aarch64 创建时刻无直接锚，由"死于创建后 15min"+死亡 11:21 反推 ≈11:06（双腿分时创建）；runner 上线无直接日志，上界取 action 默认 `runner_wait_timeout=120s` → 各腿 setup 结束 ≤ 创建+~3min（x86 ≤~11:01、aarch64 ≤~11:09）。若第三方时间戳有误，下列结论随之失效。

- **界 1（watchdog Phase-1）**：Phase 1 有界等待 `BOOTSTRAP_WATCH_TIMEOUT` 默认 **1800s**（user-data.sh:321，30min），超时自毁。死亡 14-15min < 30min → 默认下 Phase-1 超时路径不可达；除非经 /etc/environment 覆盖（user-data 仅写代理变量，需运维手工干预——列入 §6 核查清单）。
- **界 2（action 侧清理链）**：死亡时刻 x86 11:12、aarch64 11:21，距各腿 setup 结束上界分别 ≈≥11min / ≈≥12min——两腿均有充分 job 运行窗口，期间 action 侧无存活的可触发 cleanup 步骤（instance_id 仅存于 outputs）→ 此链对本次事故大概率不可达。一般性归因陈述与本次适用性分开裁决：若调用方覆盖 `runner_wait_timeout` 则等待路径可达——需查调用方工作流配置。
- **界 3（AutoReleaseTime）**：每实例无条件携带 `--AutoReleaseTime`（`INSTANCE_TTL_MINUTES` 默认 240、下限 30；create_spot_instance.py:305-316 的响亮失败语义保证 <30min 配置不可能静默通过）。死亡 14-15min < 30min → 默认与合法配置下均不可达，一行排除。
- **spot 回收（软排除）**：v1.4.0 默认 `spot_duration=1` → 本次死亡时刻落在文档保证的不回收窗口内。排除依据是**保证句+预警句的合取**（非仅预警句）；"回收事件事后在档可查"是独立前提（假定 DescribeInstanceHistoryEvents 类接口保留历史事件——假说，未取一手源），故列为高度可能排除而非绝对，最终裁决依赖 §6 的 ECS 历史事件查询。

## 5. 关键实证：post-job hook 自 initial commit 起为死配置（C-PH-INERT）

- user-data.sh:451 设置的 `ACTIONS_RUNNER_HOOK_POST_JOB` **不被 runner 读取**：S2 全库 0 命中；S1 官方变量名为 `ACTIONS_RUNNER_HOOK_JOB_COMPLETED`（ADR 逐字在档）→ post-job 自毁路径是失效的死配置。
- 血统：自 initial commit 起存在；泄漏加固 commit `6c18a60` 改动 hook 相关行而未察觉变量名错误（git -S 检索：POST_JOB 首现于 0a7de85）；**泄漏蓝图 fix-instance-leak-three-defenses-v1 的 AC-3 结构钉扎因此锁定了一条从未生效的"防线"**。
- 对候选集的影响：实例内取消→销毁 by-design 链仅经 watchdog（依赖 ephemeral 单 job 语义——高置信常识，未取一手源）；"watchdog=异常兜底、post-job=正常路径"二分法不成立。
- 部署形状注意：本部署 `./svc.sh install root`（user-data.sh:467）+ `RUNNER_ALLOW_RUNASROOT=1`（:429）——钩子本会以 root 执行，非 root 可执行性在当前部署是伪问题；若未来改非 root 服务用户，self-destruct 将在 root-only 的 `/run/self-destruct.lock`（:179-181）取锁处硬失败，需同步调整锁/日志路径。

## 6. 取证清单（下次复现时闭环）

本次无法定案的直接障碍：取证数据随实例蒸发。清单：

- **实例端**：runner-watchdog.log（加固后为三态探测时间线，见 §7 方案 D）、self-destruct.log、journalctl 的 OOM killer 记录。
- **云侧**：ECS 实例历史系统事件（DescribeInstanceHistoryEvents 类接口）——spot 预警/回收的最终裁决依据（§4 软排除的补证）。
- **调用方/环境 4 项配置**：`runner_wait_timeout`、`spot_duration`、`instance_ttl_minutes`、`BOOTSTRAP_WATCH_TIMEOUT`（后两项界算术的覆盖通道；均为调用方或运维手工覆盖位，user-data 自身不写）。
- **时间戳独立锚定**：job run 日志与实例创建/销毁时刻（本次 aarch64 创建时刻系反推、全套时间戳系转述）。

## 7. 修复决策

| 方案          | 内容                                                                                                                                                                                                          | 裁决                                                                              |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| A             | **连续 N 次确认 + 查询失败分流**：本质修法=把"查询失败"与"确认非 active"分流（systemctl 非零退出不计入停止证据）；自毁须 `STOP_CONFIRMATIONS_REQUIRED`（默认 6 × 轮询 5s = 30s）次**连续 confirmed-inactive** | **采纳**                                                                          |
| B             | GitHub API 注册态作主判据                                                                                                                                                                                     | 不采纳：dead-man switch 的本地/离线约束（防泄漏三防线血统）                       |
| C             | 最小存活 30min 一刀切                                                                                                                                                                                         | 不采纳：短 job 完成后快速回收是成本优化；若做仅限 Phase 2 异常判定且 60-120s 小值 |
| D             | **取证武装**：自毁前转储探测时间线 + systemctl/journal 尾部（大小上限），落 watchdog 日志并回显串口控制台                                                                                                     | **采纳**（本次定案障碍的直接回应）                                                |
| post-job hook | 移除而非激活（改名 `ACTIONS_RUNNER_HOOK_JOB_COMPLETED` 激活会使自毁在**同步**钩子内执行——阻塞 "Complete runner" 步骤、与 runner 自身关机→watchdog 形成删除竞态，且 /run 锁去重后零防御增量）                  | **移除**；teardown 由加固后 watchdog + AutoReleaseTime 覆盖                       |

## 8. 诚实披露与残留不确定

- **成因单因未定**：需时间戳/实例端日志裁决（§6 清单闭环后另行归档）；本文档收敛的是复核过程，不是事故真实成因（outcome 轴归人）。
- **对称假说标注**：systemd 状态抖动主张与第一方机制反驳均为无源推理假说（S4 一手手册抓取失败，纪律对双方一体适用）。
- **转述链**：第三方 T1-T5 分析与第一方 V1-V5 裁决原文系会话转述、未存档（编排者锚定；仅 V4c 裁决逐字内嵌于复核工件）；事故时间戳系第三方转述、未独立核实。
- **取证覆盖上限**：S1/S2 由编排者在线抓取存档（同源腿不可重取；异源腿文件级佐证）；M4 字节级 git diff 为编排者存档+腿内三重旁证；ephemeral "单 job 后退出"与"两取消方向 GitHub 侧表现等价"为高置信常识/常识前提，未取一手源。

## 9. 修复蓝图

修复由 [`docs/intent-blueprints/watchdog-hardening-v1.blueprint.md`](../intent-blueprints/watchdog-hardening-v1.blueprint.md)（watchdog-hardening-v1）承接：AC-1 三态探测 / AC-2 连续确认（STOP_CONFIRMATIONS_REQUIRED）/ AC-4 自毁前取证转储 / AC-5+AC-6 post-job 死配置移除与测试反向断言 / AC-9 bootstrap 期配置校验。泄漏蓝图 fix-instance-leak-three-defenses-v1 的 AC-3 已加 superseded-by 注（指向 watchdog-hardening-v1 AC-5/AC-6——该"防线"因变量名错误从未生效）。
