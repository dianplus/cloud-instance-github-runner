---
blueprint_version: v1
frozen_at: 2026-08-21
task: fix-instance-leak-three-defenses
status: frozen
---

> NOTE (2026-09-04): AC-3 superseded by watchdog-hardening-v1 AC-5/AC-6 — post-job hook was a dead config (ACTIONS_RUNNER_HOOK_POST_JOB never read by runner; see incident review).

# Intent Blueprint: 修复实例泄漏三道防线

## Background

外部项目调用本 action 时泄漏 6 台 spot 实例。调查证实三道防线全部失效：

1. `templates/user-data.sh` 以 `set -euo pipefail` 运行，自毁机制在 runner 注册（`./config.sh`）成功之后才安装（line 217+）；注册失败导致脚本早亡，自毁从未武装。
2. `scripts/cleanup-instance.sh:44-48` 用 `2>/dev/null || echo "NotFound"` 把 CLI 缺失/认证失败/网络错误全部伪装成"已删除"并 `exit 0`；无 `command -v aliyun` 预检；`Stopped` 被误判为已删除；删除后无验证。
3. `scripts/create_spot_instance.py` 的 RunInstances 无 `--AutoReleaseTime`，spot 实例无计费兜底。

附加缺陷（同批修复）：post-job-hook.sh 在 `svc.sh start` 之后才创建；备份 systemd 看门狗的 glob 等待循环在 runner 服务未出现时立即退出（race）。

## Core Use Cases

- UC-1: 实例引导失败自愈——user-data 任何阶段失败（注册失败、依赖下载失败、runner 服务从未出现），实例最终被销毁，不依赖调用方。
- UC-2: Action 清理真实可信——清理脚本要么可验证地删除实例，要么响亮失败（非零退出 + 明确错误），永不假报"已删除"。
- UC-3: 云端计费兜底——实例创建即携带 AutoReleaseTime，即使实例内所有软件机制失效，云端在 TTL 到期强制释放。

## Acceptance Criteria

### UC-1

- AC-1: Given `templates/user-data.sh`，when 检查章节顺序，then 自毁武装章节（创建 `/usr/local/bin/self-destruct.sh`、创建 `/usr/local/bin/runner-watchdog.sh`、enable 看门狗 systemd unit）整体位于章节头 `=== Installing GitHub Actions Runner ===` 之前；runner 注册调用 `./config.sh` 位于该章节头之后。即：任何 runner 相关步骤失败时，自毁与看门狗已武装。
- AC-2: Given user-data 在自毁武装之后的任何步骤失败，when 脚本以非零码退出，then `trap ... EXIT`（handler 函数名 `on_user_data_exit`）触发自毁路径；handler 必须以退出码非零为触发条件，退出码为 0 时不触发销毁；trap 安装位置不得晚于自毁武装章节结束（允许更早安装并带 self-destruct.sh 存在性守卫）。
- AC-3: Given user-data 到达 runner 服务安装，when 执行 `./svc.sh start`，then `${RUNNER_DIR}/post-job-hook.sh` 已存在（其创建位于 start 之前）。
- AC-1b（看门狗语义）: `runner-watchdog.sh` 为 dead-man 语义：在 `BOOTSTRAP_WATCH_TIMEOUT`（默认 1800 秒）内等待 `actions.runner.*.service` 变为 active；超时未出现 → 执行 self-destruct（覆盖 trap 未触发的情形，如 reboot/kill -9）；出现后转为等待其停止 → 停止即执行 self-destruct。不得使用"glob 不匹配即视为已停止"的判定。

### UC-2

- AC-4: Given `aliyun` CLI 不在 PATH，when 运行 `scripts/cleanup-instance.sh`，then 以非零码退出并输出指明 CLI 缺失的错误信息；输出中不得出现 "already deleted"。
- AC-5: Given DescribeInstances 返回 rc=0 且实例集为空，when 运行清理脚本，then 退出码 0 且报告"已确认不存在"。
- AC-6: Given DescribeInstances 命令失败（非零 rc，模拟认证/网络错误），when 运行清理脚本，then 有界重试后以非零码退出；不得把命令失败与"实例不存在"混同。
- AC-7: Given 实例状态为 `Stopped`，when 运行清理脚本，then 发起 DeleteInstance（Stopped ≠ 已删除，停机实例仍计费磁盘）。
- AC-8: Given DeleteInstance 返回成功，when 运行清理脚本，then 轮询 DescribeInstances 直至实例从结果集消失（有界重试）；超出界限实例仍存在 → 非零退出。

### UC-3

- AC-9: Given 环境变量 `INSTANCE_TTL_MINUTES`（缺省 240），when 调用 `compute_auto_release_time`，then 返回 ISO8601 UTC 格式 `yyyy-MM-ddTHH:mm:ssZ` 且秒位为 `00`、时间距 now ≥ 30 分钟；TTL < 30 分钟时响亮报错（error_exit），不得静默截断。
- AC-10: Given 任一创建路径（candidates 重试或单次），when `create_instance` 构造 RunInstances 命令，then 命令包含 `--AutoReleaseTime <计算值>`。
- AC-11: Given action.yml 的 Cleanup on Failure 步骤，when 检查其条件，then 为 `if: failure() || cancelled()`；且该步骤向 `INSTANCE_TTL_MINUTES` 之外不引入新的隐式环境假设。action 新增 input `instance_ttl_minutes`（缺省 "240"）并在 Create Spot Instance 步骤注入 `INSTANCE_TTL_MINUTES`。

## Non-Functional Requirements

- NFR-1: `bash -n` 对 `templates/user-data.sh` 与 `scripts/cleanup-instance.sh` 零语法错误。
- NFR-2: `ruff check` 与 `ruff format --check` 对 `scripts/` 干净（line-length 100）。
- NFR-3: 不新增运行时依赖（不新增 pip 包；清理路径不新增外部下载）。
- NFR-4: shell 保持 bash，兼容 GitHub Actions runner 与 Alibaba Cloud Linux 3 环境。
- NFR-5: 测试零网络、零真实云凭证（stub `aliyun`、tmp 目录）。
- 覆盖率：measure-only（主体为 bash 脚本；Python 部分由单元测试覆盖）。

## Non-Goals

- 不将清理路径改写为 Python SDK（根因是错误吞噬，非 CLI/SDK 不一致；两路径实际均已用 CLI）。
- 不新增实例内 TTL systemd timer——云端 AutoReleaseTime 是唯一硬生命周期上限（单一事实源）。
- 不修改 `select_instance.py` / `wait-for-runner.sh` 行为。
- 不在本仓库内自动删除已泄漏的 6 台实例（运维手册放最终报告）。

## Acceptance-Criteria -> Test Mapping

- AC-1 → tests/test_user_data_structure.py::test_self_destruct_armed_before_runner_install
- AC-1b → tests/test_user_data_structure.py::test_watchdog_deadman_semantics
- AC-2 → tests/test_user_data_structure.py::test_exit_trap_arms_self_destruct_on_failure
- AC-3 → tests/test_user_data_structure.py::test_post_job_hook_created_before_service_start
- AC-4 → tests/test_cleanup_instance.py::test_cleanup_fails_loudly_when_cli_missing
- AC-5 → tests/test_cleanup_instance.py::test_cleanup_exit_zero_when_instance_genuinely_absent
- AC-6 → tests/test_cleanup_instance.py::test_cleanup_fails_when_status_query_errors
- AC-7 → tests/test_cleanup_instance.py::test_cleanup_deletes_stopped_instance
- AC-8 → tests/test_cleanup_instance.py::test_cleanup_verifies_deletion_completed
- AC-9 → tests/test_create_spot_instance.py::test_auto_release_time_format_and_minimum
- AC-10 → tests/test_create_spot_instance.py::test_run_instances_command_includes_auto_release_time
- AC-11 → tests/test_action_workflow.py::test_cleanup_step_runs_on_failure_or_cancelled

结构类 AC（AC-1/1b/2/3）为模板文本的结构性验证——user-data.sh 在云端 cloud-init 内执行，无法在本仓无凭证环境做行为级测试；测试以章节锚点与行序断言编码契约，此为诚实的覆盖上限，语义残差归外环评审。
