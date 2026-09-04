---
blueprint_version: v1
frozen_at: 2026-09-04
task: runner watchdog 加固（查询失败分流 + 连续确认）与 post-job 死配置移除
status: frozen
---

# Intent Blueprint: watchdog 加固与 post-job 死配置移除

> 背景（2026-09-03 事故复核，csr 收敛记录：workspace/cross-source-review/runs/20260903-222855-watchdog-review-verify/convergence-record.json）：job 运行中实例被销毁、job 报 cancel 的事故，经同源+异源复核收敛后的候选集为：上游取消→watchdog（by-design）/ watchdog 误杀（查询失败型或瞬态）/ OOM→真实停止 / spot 回收仅当 1 小时保证不兑现。复核同时实证：`ACTIONS_RUNNER_HOOK_POST_JOB` 不被 actions/runner 读取（全库 0 命中，官方变量为 ACTIONS_RUNNER_HOOK_JOB_COMPLETED）——本仓库 post-job hook 自 initial commit 起为失效死配置；泄漏蓝图（fix-instance-leak-three-defenses）AC-3 的结构钉扎锁定了这个从未生效的"防线"。

## Sources

- **S1 actions/runner ADR 1751-runner-job-hooks.md**（编排者 2026-09-03 在线取证逐字归档，同源腿不可重取——依赖本存档与 S4 记录的异源文件级佐证）：官方钩子变量为 `ACTIONS_RUNNER_HOOK_JOB_STARTED` / `ACTIONS_RUNNER_HOOK_JOB_COMPLETED`；钩子为**同步**执行、阻塞 job、以 Runner 用户身份。
- **S2 actions/runner 代码检索**：`ACTIONS_RUNNER_HOOK_POST_JOB` 全库 0 命中；JOB_COMPLETED 3 命中（JobExtension.cs 等）。
- **S3 本仓库 v1.5.0 源码**：templates/user-data.sh（watchdog 相位/探测函数/`2>/dev/null` 吞错/单次命中即毁；post-job hook 死配置 :450-465（:450 误导注释、:451 export、:455-465 hook 块）；`svc.sh install root` :467）；tests/test_user_data_structure.py（AC-3 结构钉扎）；scripts/wait-for-runner.sh:12 过时注释（"Default timeout 5 minutes" 实为 120s）。
- **S4 事故复核工件**（上文收敛记录）：watchdog 探测把"查询失败"与"确认非 active"混同为一谓词（空≡非active）是误杀候选的代码形状根因；取证数据随实例蒸发是定案障碍。

## Core Use Cases

- UC-1: watchdog Phase 2 判定"runner 已停"须以**连续 N 次确认非 active**为准，且**查询失败（systemctl 非零退出）不构成停止证据**——重载下的瞬时查询故障不再可能单次命中即毁实例。
- UC-2: 移除 post-job hook 死配置（变量名错误、从未生效），修正相关注释与结构测试——防线集实际构成（EXIT trap + watchdog + action 失败清理 + AutoReleaseTime）不变。
- UC-3: 自毁触发前**武装取证**：探测历史与系统状态转储落日志并回显串口控制台（GetInstanceConsoleOutput 可在删除前抓取）。
- UC-4: 非法配置响亮失败；既有防线语义（Phase 1 有界等待、EXIT trap、AutoReleaseTime 下限）零回归。

## 设计决策（显式声明，防误改）

- **三态探测**：`systemctl list-units` 退出码 0 且输出非空=active；退出码 0 且输出空=**confirmed-inactive**；非零退出=**unknown**（查询失败）。unknown **既不递增也不重置**连续计数（查询抖动不应无限延长确认窗，也不应抹掉已积累的确认证据；泄漏侧由 AutoReleaseTime 兜底）。
- **连续确认**：`STOP_CONFIRMATIONS_REQUIRED`（默认 6 × POLL_INTERVAL_SECONDS 5s = 30s）次**连续 confirmed-inactive** 才自毁；出现 active 即清零重计。默认值可经 /etc/environment 覆盖（与 BOOTSTRAP_WATCH_TIMEOUT 同机制）。
- **Phase 1 不变**：有界等待 BOOTSTRAP_WATCH_TIMEOUT（默认 1800s）；探测三态化后 unknown 归入"继续等待"（与现行为等价，语义显式化）。
- **移除而非激活 hook（显式决策）**：改名激活会使自毁在同步钩子内执行——阻塞 "Complete runner" 步骤、与 runner 自身关机→watchdog 形成删除竞态，且 /run 锁去重后零防御增量；watchdog（修复后）+ AutoReleaseTime 已覆盖 teardown。故删除脚本/导出/注释，并以本蓝图显式取代泄漏蓝图 AC-3 的结构钉扎（该"防线"从未存在）。
- **取证武装（方案 D）**：自毁前把最近探测决策时间线（active/inactive/unknown 带时间戳）、`systemctl status` 尾部、`journalctl` 尾部写入 /var/log/runner-watchdog.log 并 `tee` 到 /dev/console（串口输出存续至实例删除（**假说，待 Rollout 取证演练实证**——tee /dev/console 在末秒的输出能否被 GetInstanceConsoleOutput 抓到、缓冲窗口多大，均未取一手源）；**竞态如实披露**：action 失败路径的 fetch-console-output（最坏 ≈40s 阻塞）与自毁时点（30s 确认 + 10s 等待）并发，fetch 可能输掉竞态（两落点同随实例蒸发——本地日志的实际价值如实重述：仅服务于取证演练的 SSH 直读，与**自毁失败**场景——DeleteInstance 失败时实例存活、日志可查）；转储各段带大小上限（head/tail -c，合计 ≤16KB——**设计预算**，非串口缓冲实测边界）。不引入网络外发依赖（dead-man switch 本地约束）。
- **驱动性最小改动**：不动 select/create 脚本、action.yml；user-data.sh 仅改五处：① watchdog heredoc；② hook 段落及其 :153/:294/:388 引用点（post-job 措辞清除）；③ self-destruct heredoc 内 :177-178 竞态注释（去 post-job 措辞——逻辑零变更）；④ **bootstrap 段新增 STOP_CONFIRMATIONS_REQUIRED 校验块**（位置钉扎：`trap on_user_data_exit EXIT` 之后、watchdog heredoc 之前）；⑤ wait-for-runner.sh 注释。

## Acceptance Criteria

- AC-1: 探测函数三态化：退出码非零 → unknown（不得计入停止证据）；退出码 0 + 空输出 → confirmed-inactive；退出码 0 + 非空 → active。`2>/dev/null` 吞错不再使"查询失败≡非active"。
- AC-2: Phase 2 自毁条件 = 连续 STOP_CONFIRMATIONS_REQUIRED（默认 6）次 confirmed-inactive；期间任一 active 清零；unknown 不递增不清零。变量默认 6、可环境覆盖。
- AC-3: Phase 1 语义保持：BOOTSTRAP_WATCH_TIMEOUT 默认 1800s 有界等待；超时自毁路径不变；unknown 归入继续等待。
- AC-4: 自毁前取证转储：探测时间线（含三态与时间戳）、systemctl status 尾部、journal 尾部 → /var/log/runner-watchdog.log + /dev/console；转储失败不得阻断自毁（best-effort）。
- AC-5: post-job hook 死配置整体移除：user-data.sh 不再出现 ACTIONS_RUNNER_HOOK_POST_JOB、post-job-hook.sh heredoc、及其误导注释；.env 导出行移除；`./svc.sh start` 前的既有次序断言以"不存在 hook"形态取代。
- AC-6: tests/test_user_data_structure.py 的泄漏蓝图 AC-3 钉扎更新为反向断言（无 POST_JOB 残留）；其余既有结构测试零回归。
- AC-7: scripts/wait-for-runner.sh:12 注释修正为与 TIMEOUT 默认 120 一致。
- AC-8: docs/postmortem/2026-09-03-runner-shutdown-incident-review.md 落档（由收敛复核工件改编：候选集、排除算术、取证清单、修复决策）；CHANGELOG [Unreleased] 条目；泄漏蓝图（fix-instance-leak-three-defenses-v1）经 Revision Channel 为其 AC-3 加 superseded-by 注（指向本蓝图 AC-5/AC-6，记录"防线因变量名错误从未生效"）；tests/test_user_data_structure.py 文件头 docstring 的 AC-3 标签同步更新。（文档，人工核对）
- AC-9: STOP_CONFIRMATIONS_REQUIRED **校验对象=操作员逃生舱通道的值**：user-data bootstrap 期（`trap on_user_data_exit EXIT` 之后、watchdog heredoc 之前）以钉扎读取形状从 /etc/environment 取该键：**锚定 `^STOP_CONFIRMATIONS_REQUIRED=` + `tail -1`（重复键取尾，与 systemd 后行覆盖语义一致）+ `cut -d= -f2-` + 剥双引号（`tr -d '"'`，兼容本文件既有带引号写入约定）**，随后校验剥引号后值为正整数；非正整数 → 打印 error 并以非零退出 user-data——EXIT trap 随即触发自毁（响亮且实例不残留）；键缺失 → 采用默认 6（合法路径，非静默回退——缺失即未表达覆盖）。**不得**放在 watchdog 运行期退出（Restart=on-failure 会把非零退出循环至 start-limit 后置 failed——dead-man 静默死亡）。**范围披露**：① bootstrap 之后的 /etc/environment 改写不在守护范围（与 BOOTSTRAP_WATCH_TIMEOUT 同界）；② **前导空白键行越界**：systemd EnvironmentFile 容忍前导空白，而锚定 grep 不可见——此类行将使 bootstrap 校验默认 6、watchdog 消费越界值（静默分叉残余）；契约声明：覆盖键必须行首锚定写入（本文件写入器自身满足），越界写法风险自担并在此披露。

## Non-Functional Requirements

- NFR-1: 零新增依赖；user-data 变更仍为纯 bash + 既有工具（systemctl/journalctl/tee）。
- NFR-2: ruff 不涉及（模板 bash）；`bash -n` 零语法错误（模板提取段 + 生成脚本）；pytest 全绿。
- NFR-3: 测试零网络零凭证（结构断言沿用 test_user_data_structure.py 模式）。
- NFR-4: watchdog 无 `set -e`（既有约定：探测失败不得静默死锁）。

## Non-Goals

- 不激活 ACTIONS_RUNNER_HOOK_JOB_COMPLETED（理由见设计决策；未来若要激活须独立蓝图评审同步删除竞态）。
- 不实现网络外发取证（SLS/tag）——保持 dead-man 本地约束。
- 不改 BOOTSTRAP_WATCH_TIMEOUT/POLL_INTERVAL_SECONDS 默认值。
- 不在本蓝图裁决事故真实成因（取证清单闭环后另行归档）。

## Acceptance-Criteria -> Test Mapping（RED 阶段冻结）

- AC-1 → tests/test_user_data_structure.py::test_watchdog_probe_distinguishes_query_failure
- AC-2 → tests/test_user_data_structure.py::test_watchdog_requires_consecutive_confirmations
- AC-3 → tests/test_user_data_structure.py::test_watchdog_phase1_semantics_preserved
- AC-3 粒度注（非映射行）：断言 BOOTSTRAP_WATCH_TIMEOUT 默认 1800 文本在档、超时分支 exec self-destruct 形状保留、三态探测下 unknown 归入继续等待（sleep 循环）分支形状；新断言并入 test_watchdog_phase1_semantics_preserved；既有 test_watchdog_deadman_semantics 测试原样保留、零删改。
- AC-4 → tests/test_user_data_structure.py::test_watchdog_pre_destroy_forensics_dump
- AC-5/AC-6 → tests/test_user_data_structure.py::test_post_job_hook_dead_config_removed
- AC-7 → tests/test_wait_for_runner.py::test_timeout_comment_matches_default
- AC-9 → tests/test_user_data_structure.py::test_watchdog_invalid_confirmations_fails_loudly

AC-9 粒度注（非映射行）：断言校验块位于 `trap on_user_data_exit EXIT` 之后、watchdog heredoc 之前（置于 trap 之前的参数校验区（:33-47）会使非零退出时 trap 未装、实例静默泄漏——位置钉扎防该错位）；含从 /etc/environment 读该键的钉扎形状（锚定+tail+cut+剥引号）、正整数校验形状、非零退出、**缺失键分支的守护形状**（if-grep 守护或 `|| true`——模板 `set -euo pipefail` 下未守护的无匹配 grep 会使 user-data 非零退出=『缺失键→自毁』反语义，断言缺失路径无 exit 且默认 6 文本在档）；反向断言校验不出现于 watchdog 脚本内（避免 Restart=on-failure 循环）。

- AC-8 → 无自动化测试（文档，人工核对——Coverage Notes；映射顺序先行于 AC-9 行仅因编号列示）

## 用例粒度注（非映射行）

- test_watchdog_probe_distinguishes_query_failure：断言探测函数含退出码捕获（如 `rc=$?` 或 `if ... ; then` 形状）与三态输出词（active/confirmed-inactive|inactive/unknown）；断言自毁条件分支仅以 confirmed-inactive 计数。
- test_watchdog_requires_consecutive_confirmations：断言 STOP_CONFIRMATIONS_REQUIRED 默认 6、连续计数变量形状、active 清零分支；30s 算术（6×5）注释在档。
- test_post_job_hook_dead_config_removed：反向断言 POST_JOB 变量、post-job-hook、.env 导出、以及 **post-job 字样全词零出现**（覆盖四处注释/回显 :153/:177/:294/:388——其中 :177 在 self-destruct heredoc 内，已获区域③显式授权）；章节次序锚由既有 test_self_destruct_armed_before_runner_install 承担（非 svc.sh start 次序——该锚随 hook 移除而消亡）。
- test_watchdog_pre_destroy_forensics_dump：断言转储函数形状——探测时间线记录（三态+时间戳进 log）、`systemctl status` 与 `journalctl` 尾部采集（带大小上限 head/tail -c 形状）、输出同时落 /var/log/runner-watchdog.log 与 /dev/console（tee 形状）、best-effort 包裹（转储分支失败不得阻断自毁 exec）。
- 结构测试基线：既有 test_self_destruct_armed_before_runner_install / test_watchdog_deadman_semantics / test_exit_trap_arms_self_destruct_on_failure 零回归（本蓝图 AC-3 断言并入 phase1 测试后原断言保留）。

## Rollout 验证（实施后）

- 正常路径灰度：job 完成 → 实例应在 ~30-40s（6 次确认 + 10s self-destruct 固定等待）内自毁（现基线 ≈ 最多 ~15s：≤5s 轮询 + 10s 等待；增量 ≈ +25s，按秒计费下成本可忽略）。
- 取证演练：人为 `systemctl stop actions.runner.*` 前注入负载，核对 runner-watchdog.log 时间线含三态记录、串口可经 GetInstanceConsoleOutput 抓到转储；另演练取消路径下 fetch 与自毁的时序（fetch 是否在删除前完成——竞态披露的实证）。
- 事故候选集取证清单（runner-watchdog.log / self-destruct.log / journal OOM / ECS 历史事件 / 调用方 4 项配置）随下次复现闭环。

## Coverage Notes

AC-8（postmortem 文档 + CHANGELOG）无自动化测试，人工核对。泄漏蓝图（fix-instance-leak-three-defenses）AC-3 的结构钉扎由本蓝图 AC-5/AC-6 显式取代：该"防线"因变量名错误从未生效（S1/S2 实证），移除不改变实际防线构成。
