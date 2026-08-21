# Postmortem: Spot 实例泄漏——三道防线同时失效

- 日期: 2026-08-21
- 状态: 已修复（commit `6c18a60`）；存量泄漏实例已于 2026-08-21 手动清算完毕
- 影响: 外部项目调用本 action 期间泄漏 6 台 Aliyun ECS spot 实例，持续产生按量计费
- 严重度: High（资源泄漏 + 计费损失；无数据/安全影响）

## 1. 概要

外部项目通过本 action 创建 spot runner 实例。runner 注册因代理不通而失败后，6 台实例全部未被销毁。调查证实：设计上存在的三道防线彼此独立地全部失效，且失效模式互为盲区——实例内自毁只保护"装好之后"，action 清理谎报成功，云端计费兜底根本不存在。

## 2. 时间线（外部项目视角）

| 时间 (UTC)   | 事件                                                                                                                            |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| ~00:2x       | 6 次 action 调用各自创建 spot 实例成功                                                                                          |
| ~00:2x       | 实例 user-data 执行：依赖安装成功，`config.sh` 注册 github.com 失败（代理不通），`set -euo pipefail` 终止脚本——自毁机制尚未安装 |
| 00:30:10.564 | action 清理步骤打印 "Checking instance status..."                                                                               |
| 00:30:10.582 | 18ms 后打印 "Instance already deleted or not found"，exit 0                                                                     |

> 取证限制：18ms 往返无法完成真实 API 调用，与 `command not found` 被吞的特征吻合，属高置信推断而非可复现证据（外部日志本仓库不可达）。无论真实成因是 CLI 缺失还是 CLI 快速失败，修复后的清理脚本对两种情形都响亮失败，方案对该归因不敏感。

## 3. 三道防线失效分析（修复前代码证据）

### 防线 1: 实例自毁——保护范围假设错误

- 预期: 实例生命周期结束后自毁。
- 实际: 自毁脚本、post-job hook、systemd 备份服务全部位于 `./config.sh` 注册**之后**安装（旧 `templates/user-data.sh:217+`）。注册失败 → `set -e` 在武装前终止脚本 → 自毁机制从未存在。
- 缺陷本质: 自毁只覆盖"装好之后"，对"装不上"零保护——保护范围与失效场景恰好不相交。

### 防线 2: action 失败清理——错误吞噬制造假绿

- 预期: 创建失败/runner 未上线时删除实例。
- 实际: 旧 `scripts/cleanup-instance.sh:44-48` 用 `2>/dev/null || echo "NotFound"` 把 CLI 缺失、认证失败、网络错误、查询解析失败全部伪装成"实例不存在"→ exit 0。脚本无 `command -v aliyun` 预检；`Stopped` 状态被误判为已删除（停机实例仍计费磁盘）；DeleteInstance 成功后无任何验证。
- 缺陷本质: 清理路径上"报成功"不需要任何证据，静默失败被系统性奖励。

### 防线 3: 云端计费兜底——不存在

- 预期: （设计上缺失）
- 实际: `create_spot_instance.py` 的 RunInstances 无 `--AutoReleaseTime`。spot 实例（PostPaid）支持该参数，却从未设置——所有软件机制失效时无任何硬性释放保证。
- API 语义核验: AutoReleaseTime 仅适用于按量付费（PostPaid，spot 属之）、至少 30 分钟后、ISO8601 UTC——已对阿里云官方 RunInstances 文档核验（help.aliyun.com，2026-08-21）。

### 调查中发现的附加缺陷（同批修复）

1. post-job-hook.sh 在 `svc.sh start` 之后才创建，而 `.env` 在服务启动前就引用它（首任务若早到则 hook 缺失）。
2. 备份 systemd 服务的 `while systemctl is-active --quiet actions.runner.*` 循环：runner 服务未出现时 glob 不匹配 → 立即视为"已停止"→ 开机即自毁（race）。
3. 清理步骤仅 `if: failure()`，未覆盖 `cancelled()`。
4. 原报告旁证勘误（原始事故报告 = 外部项目调用方的运行日志分析，非本仓库文档）："创建走 Python SDK"不成立——创建同为 subprocess 调 aliyun CLI；技术栈一致，缺陷在错误吞噬本身。

## 4. 根因归纳

1. **顺序假设**: 引导脚本默认"后续步骤必然成功"，把安全机制排在最脆弱步骤（外部网络注册）之后。
2. **错误吞噬模式**: `|| echo` 兜底把所有失败折叠为一个成功路径，使清理永远"绿"。
3. **缺失纵深**: 无云端硬释放兜底，防线上不存在与实例内状态无关的最后保障。
4. **触发面缺口**: 清理仅挂 `if: failure()`——cancelled 的运行完全不触发清理（本事件中未成为直接成因，属同批修复的同类系统性缺口）。
5. **流程根因**: 失败路径零测试覆盖——清理脚本在无 CLI、查询失败、删除后未消失等场景下从未被验证过。

> 行号证据核验: 修复前代码引用（§3 的旧 `cleanup-instance.sh:44-48` 与旧 `user-data.sh:217+`，精确定位为 `templates/user-data.sh` 内 `./config.sh` 注册调用位于 187 行、自毁安装章节起于 218 行）已经 git 历史对照核验（`git show 6c18a60^`），与文档描述逐字一致。

## 5. 修复内容（commit `6c18a60`）

| 防线                                        | 修复                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. `templates/user-data.sh`                 | 自毁武装整体前置到 runner 安装之前；EXIT trap（`on_user_data_exit`，非零退出即后台触发自毁，保留退出码）；dead-man 看门狗（`runner-watchdog.sh`，`BOOTSTRAP_WATCH_TIMEOUT=1800s` 有界等待 runner 服务出现、超时即毁、出现后停止即毁；systemd 侧模式匹配消除 glob race；`Restart=on-failure` 防单发射耗尽）；post-job-hook 先于服务启动创建；flock 锁移至 root-only `/run/` |
| 2. `scripts/cleanup-instance.sh`            | CLI 预检缺失即响亮失败；原始 JSON 查询 + python3 解析；命令失败 ≠ 不存在（`CLEANUP_MAX_ATTEMPTS` 有界重试后非零退出）；`Stopped` 照删；删除后轮询验证实例真正消失（`CLEANUP_VERIFY_POLLS`）；全文件禁用 "already deleted" 措辞                                                                                                                                             |
| 3. `create_spot_instance.py` + `action.yml` | RunInstances 无条件携带 `--AutoReleaseTime`（分钟向上取整保证 TTL=30 边界严格 ≥30min；非整数 TTL 响亮报错）；新 input `instance_ttl_minutes`（默认 240）；清理步骤改 `if: failure() \|\| cancelled()`                                                                                                                                                                      |

修复后泄漏窗口：实例内机制全失效的最坏情形下，实例在创建时 + TTL 被云端强制释放。

## 6. 验证

仓库内可复核载体（提交物）：

- 12 条 AC 映射的回归测试（蓝图 `docs/intent-blueprints/fix-instance-leak-three-defenses-v1.blueprint.md` 的 AC→Test Mapping 1:1），stub 忠实模拟真实 aliyun CLI 语义（`--query` 无匹配 rc=1），杜绝假绿路径。
- `tests/test_create_spot_instance.py::test_auto_release_time_random_boundary_property`: ceil 边界属性测试（2 万固定种子随机样本，任意小数秒 now 下 release ∈ [now+ttl, now+ttl+60s)）。
- `tests/test_generate_user_data.py`: sed 注入契约测试——运行真实 `generate-user-data.sh`，锁定 9 个注入变量的契约（8 个注入值全部落入渲染产物 + 1 个未注入可选变量 RUNNER_LABELS 保持模板默认行），产物 `bash -n` 通过。

会话过程记录（仓库无载体，不可复核，如实区分）：

- TDD RED→GREEN 计数（RED 11 failed/1 protected-green → GREEN 12/12）、内环各工具零错输出、外环独立 code-reviewer 两轮（全量 + delta，12/12 AC satisfied）、外环一次性 20 万样本边界抽查。上列数字以会话运行记录为准；其可复核的沉淀物是测试与蓝图本身。

## 7. 存量泄漏实例清算手册（手动执行）

新防线仅保护未来创建的实例。泄漏实例均带标签 `GITHUB_RUNNER_TYPE=aliyun-ecs-spot`：

```bash
# 1. 每个在用 region 扫描泄漏实例
aliyun ecs DescribeInstances --RegionId <region> \
  --Tag.1.Key GITHUB_RUNNER_TYPE --Tag.1.Value aliyun-ecs-spot

# 2. 核对列表（确认非他人正当使用的 runner）后逐台删除
aliyun ecs DeleteInstance --RegionId <region> --InstanceId i-xxx --Force true
```

> 官方限制: 单标签过滤最多返回 1000 条（DescribeInstances 文档核验），超过需按 zone/分页细分扫描。标签过滤语法 `Tag.1.Key/Tag.1.Value` 已对官方文档核验。

## 8. 残差与已知债（诚实披露）

- 已接受残差: ~~cloud-final 的 cgroup KillMode 策略可能终止 trap 的 nohup 进程~~（已消除：trap 改经 `systemd-run` 瞬态单元触发自毁，独立 cgroup 不受 cloud-init 收尾影响，保留 nohup 回退）；实例被并发释放时清理措辞可能误导（方向安全，永不假绿）。
- 已知债: `scripts/select_instance.py` pyright 报 7 条类型错误（修复时快照计数，未建 baseline 固化、随 pyright 版本浮动；修复需行为性守卫，超出本次冻结范围）。**该债已于 2026-08-21 由 commit `521d97e` 清偿**（NoReturn 收窄 + 空串守卫，全仓 pyright 归零），此处保留为历史记录。
- 结构测试上限: user-data.sh 在云端 cloud-init 内执行，AC-1/2/3 为结构锚点验证，运行时语义经外环推演复核而非行为级执行。
- 引用覆盖上限: §3/§7 的阿里云官方文档主张（AutoReleaseTime 语义、Tag 过滤与 1000 条上限）系会话内 WebFetch 核验，原文未内联入文档——跨源评审者无法独立复审，属已知引用覆盖上限。

## 9. 行动项

| #   | 项目                                                                         | 状态               |
| --- | ---------------------------------------------------------------------------- | ------------------ |
| 1   | 三道防线修复 + 12 回归测试                                                   | 完成（`6c18a60`）  |
| 2   | 手动清算 6 台泄漏实例（§7 手册）                                             | 完成（2026-08-21） |
| 3   | 可选: 按标签定期巡检的云端扫描（超出本仓库范围，建议在账户侧以运维规则实现） | 建议               |

## 10. 经验教训

1. 自毁/清理类安全机制的安装位置必须先于其要保护的失败模式可能发生的位置——"先武装，再冒险"。
2. 清理路径的成功必须以证据（复询验证）为前提，`|| echo` 式兜底会把最需要响亮的失败变成最安静的假绿。
3. 计费资源必须有与软件状态无关的云端硬释放兜底（AutoReleaseTime / 生命周期策略）。
4. 失败路径需要与成功路径同级的测试覆盖；stub 模拟真实工具的失败语义（如 CLI 的 rc 约定）是防假绿的关键。
