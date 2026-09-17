---
blueprint_version: v1.1
frozen_at: 2026-09-17
revised_at: 2026-09-17
task: PR#2 maintainer 干预——watchdog 窗口可配化 + bootstrap 包处理极简 + runner 版本自动策略
status: frozen
---

# Intent Blueprint — PR#2 maintainer 干预

This blueprint is the FROZEN, read-only anchor for the convergence loop. The Coder cannot edit it. Reviewer must diff every change against it. To change intent, use the Blueprint Revision Channel (status -> revising -> Planner+human -> version bump -> re-freeze). See references/intent-blueprint.md.

> 修订记录 v1→v1.1（2026-09-17，经用户授权，plan-reviewer 外环 round-1 verdict=rewrite 后修订）：吸收 11 条 findings——补齐第三处版本钉扎点（generate-user-data.sh sed 与模板默认行的锁定耦合，升为 AC-4 显式面）；postmortem（AC-8）/CHANGELOG（AC-9）从 UC 承诺落为 AC；README 覆盖面从单一 420 行扩为双语四项（AC-6）；AC-1 验证契约由 README 名测试改为人工核对（沿 watchdog-hardening AC-8 先例，README :435 钉扎移入 AC-6）；落地基线显式（基线=f364434，落地机制不属冻结范围，commit 拆分为卫生建议非契约）；action.yml runner_version default 移除显式化（空路径可达）；AC-5 写入位置锚定 trap 后/校验前 + 正整数校验 + 优先级声明；ensure_cmd 收敛为 apt/yum 两分支（删投机性 dnf）；测试基线 61 附实证出处。设计方向、架构取舍、ceil-秒制 input、fallback 软纪律均维持（外环明确未推翻）。

## 落地基线（显式）

- **基线 = PR #2 head `f364434`**（fix/automatic-updates-under-a-job）。本文档全部行锚按该基线切（master 与之差 +21 行：unattended 块 13 + watchdog 注释 8）。
- watchdog-hardening 蓝图在该基线上为 **v1.1**（master 为 v1）；本干预经修订通道在其上升 **v1.2**。
- **落地机制（PR#2 分支直推 / 独立分支）不属本蓝图冻结范围**——maintainer 决策，记录于收敛报告。commit 拆分（事实修正 / 包处理 / 版本策略 / 可配化）为提交卫生建议，契约以 AC 为准。

## 背景

PR #2（head f364434）经四源评审收敛：同源外环（GLM 家族独立上下文）、异源对抗（DeepSeek，ADR #40，round 1）、Pi 移植评审、确定性层（pytest/ruff/bash -n 三树全绿）。代码与测试半边（6→24 re-pin，双向 RED-check 证明）成立；缺陷集中在修订注因果叙事（异源 blocker-1：20s 数据与"job 到达触发"算术矛盾）、文档传播（蓝图 :35/:75/:89 三处陈旧、README 双语 :435 残留 6）、未注册变更（unattended 块零 AC 零钉扎）与根因未除（runner_version 钉扎陈旧）。

**实测取证（2026-09-17，本仓库探针分支，run 35233196551 / 35234317050）**：真实公共镜像 `ubuntu_24_04_x64_20G_alibase_20260828.vhd` 上：

- `unattended-upgrades 2.9.1` 已装且 enabled；`APT::Periodic::Unattended-Upgrade "1"`（20auto-upgrades + 10periodic 双确认）——阿里云未做禁制定制
- `apt-daily.timer` / `apt-daily-upgrade.timer` enabled；**LAST = 2026-08-28 10:20:37 CST = 镜像构建时刻**（`Persistent=true` 冻结时间戳随镜像继承 → 每次开机即进入 catch-up 待发）
- elapse 随机重排实测：+74s → 重排 +17min，+10min 时仍未发——点火时点随机分布于开机后分钟至几十分钟
- 镜像内阿里云组件仅 aegis + aliyun-assist（无补丁器）；官方文档不载镜像内部机制，实例内补丁属客户责任
- 调用方舰队（私有，匿名）6 个月 23 run 零观察与机制低可达率自洽：需 catch-up 落在 runner 注册后窗口 × 积压含 systemd/libc × 秒级 resolved 断流 × DNS 查询恰落入，四重巧合；首要冲突面实为 bootstrap 期 dpkg 锁竞争
- `actions/runner` `releases/latest` 重定向实测 = v2.337.0（2026-09-17，本蓝图探测机制同款验证）
- GitHub 侧 AK 无 DeleteInstance 权限（Forbidden.RAM）——实例删除依赖实例自毁角色 + AutoReleaseTime，设计如此

## Sources

- S1: 探针串口原始输出（run 35234317050 log，含 timer 表 / journal / systemd 状态）
- S2: docs/intent-blueprints/watchdog-hardening-v1.blueprint.md（基线上 v1.1，本次经修订通道升 v1.2）
- S3: https://github.com/actions/runner/releases/latest 重定向（fallback 常量取值依据）
- S4: https://help.aliyun.com/zh/ecs/user-guide/public-mirroring-overview（负空间证据：镜像内部机制不载）
- S5: .github/workflows/smoke-test.yml（runner_wait_timeout=420 自验值；月度真机验证惯例）
- S6: tests/test_generate_user_data.py 注入契约 docstring（generate-user-data.sh 与模板 `${VAR:-...}` 默认行的锁定耦合——本干预第三处钉扎点的依据）

## Core Use Cases

- UC-1: 调用方可以 input 收紧/放宽 watchdog 停止判定窗（代理质量自知），缺省 120s
- UC-2: bootstrap 不做系统级包操作；必要工具（curl/git）守卫式按需安装，镜像已备则零包调用
- UC-3: `runner_version` 缺省自动跟随 GitHub 在发的最新非 prerelease 版（探测在 proxy 生效范围内），显式钉扎优先
- UC-4: PR#2 遗留的全部文档/注册缺陷（蓝图三处陈旧、README 双语、postmortem、修订过程痕迹、CHANGELOG 契约）一并修正
- UC-5: 等待 runner 上线的默认超时与自身 smoke-test 自洽（420s）

## 设计决策（显式声明，防误改）

1. **窗口语义 = 最长连续不活跃确认窗**，非强制守望：三态活探测，窗内任一 active 即清零跳出（PR#2 三态设计不变）。成功路径（`--ephemeral` 单 job 退出，基线 :549）烧满窗口为**已知残留**——"永久退出"与"自更新中途暂停"在 systemctl 探测层不可区分；终态判别器（`ACTIONS_RUNNER_HOOK_JOB_COMPLETED` 标志文件 + watchdog 短路，非同步自毁、不阻塞、无删除竞态——绕开 watchdog-hardening"移除而非激活 hook"决策的全部反对理由）立 follow-up 蓝图 `watchdog-fast-teardown-v1`，不入本次。Input 文档（action.yml description + README 双语行）必须写 "max seconds of continuous inactivity"。
2. **默认 24（120s）维持**：成本不对称——放宽代价分钟级空转（spot 按秒计费），收窄代价误杀整 job；UC-3 落地后自更新触发基本消失，窗口仅为 fallback 启动与版本滚动残余场景的保险。
3. **ensure_cmd 守卫式按需安装**替换 `=== Updating system ===` 整块（基线 :106-118）：`yum update -y` 全量升级对单 job 临时实例纯损耗；`apt-get update` 仅在确有缺失安装时作为紧邻前置。**两分支**（apt 族 / yum 族——alinux 的 yum 即 dnf 后端符号链接，不设投机性 dnf 分支）。wget 从清单删除（全模板零消费者）。实例侧无 python3/jq 依赖（aliyun CLI 为 Go 二进制，实例侧脚本纯 bash）。
4. **unattended 禁用保留**（探针实证机制真实：每开机带 ~3 周积压 + catch-up 待发，生产走代理点火即真装）但移入 `command -v apt-get` 守卫：yum 分支不再 no-op + 误导横幅 + 裸 systemctl（对齐 .cursor/rules/03-shell-compatibility）。
5. **auto-latest 在 host 侧、proxy 生效范围内执行**：resolve 步骤 env 显式携带 `http_proxy/https_proxy/no_proxy` 三 input（否则 VPC 内 self-hosted agent 恒败恒落 fallback——最需要它的舰队恰好得不到）。host 侧 curl 依赖有先例（wait-for-runner.sh:46）。**action.yml `runner_version` input 的 `default: "2.330.0"` 移除**（无 default → 空值路径可达，resolve 步骤 owns 缺省）。
6. **用 `/releases/latest` 重定向而非 api.github.com**：一次 HEAD 剥 302 Location 中的 tag；零鉴权、零 JSON（模板侧不假设 jq）、不吃 60/hr 未鉴权限额（共享 NAT 下并发矩阵可打爆）；天然指向最新非 prerelease（次级版本稳健语义）。对 v3 前跳立即跟进——单 job 临时实例无长存资产需要稳定，钉扎者自有显式 input。
7. **fallback 单点**：`RUNNER_FALLBACK_VERSION` 常量（action.yml 内单一位置，初始 2.337.0），抬升纪律 = CHANGELOG 软约束（不引入会偶红的外部依赖硬门——GitHub 不可达路径本就由窗口兜底）。**版本钉扎共三处，本干预全部处理**：action.yml input default（移除）、模板 `RUNNER_VERSION:-2.311.0` 兜底（改为空默认 + 空值响亮退出守卫——host resolve 保证非空，模板守卫为防御纵深）、**generate-user-data.sh sed 模式（与模板新默认行锁定同步改写**——注入契约见 S6；不同步则注入静默失效，正是本蓝图反对的静默分叉形态）。降级要响：探测失败 `::warning::` + 落 fallback，不静默。
8. **`runner_wait_timeout` 默认 120 → 420**：smoke-test 自身注释承认"cold bootstrap via proxy 3-6 min，120s 会杀健康 run"且自验传 420——默认值过不了自身 smoke-test 属文档化自相矛盾；smoke-test 显式 420 传参与其 :76-78 的"120s default would kill"注释一并移除。
9. **watchdog 窗口 input 的传递链与写入位置**：`WATCHDOG_STOP_WINDOW_SECONDS`（input，秒）→ generator sed 注入（模板新增 `${WATCHDOG_STOP_WINDOW_SECONDS:-}` 默认行，同步进 sed 集）→ 模板在 **`trap on_user_data_exit EXIT`（基线 :300）之后、AC-9 校验块（基线 :313-320）之前**以行首锚定 append 写 `/etc/environment` 的 `STOP_CONFIRMATIONS_REQUIRED=<ceil(N/5)>`（写入位于 trap 后 = 追加失败经 trap 自毁，不复发"trap 前静默泄漏"形态；位于校验前 = action 写入值同样受 AC-9 正整数校验管辖）。模板侧校验 N 为正整数，非法 → 响亮非零退出（trap 自毁，与仓库 fails-loudly 惯例一致）。**优先级声明**：自定义镜像预置的 `/etc/environment` 同键值被 action 追加行覆盖（append + `tail -1` 后行胜 = 显式 input 优先）——期望语义，显式声明。
10. **CHANGELOG 分类契约**：Added（`watchdog_stop_window_seconds` input）/ Changed（`runner_version` 缺省语义 → auto-latest；`runner_wait_timeout` 默认 420）/ Fixed（PR#2 原 two entries 保留并入 + 事实修正 pass 的措辞收敛）。

## Acceptance Criteria (BDD)

- AC-1: Given watchdog-hardening v1.1 蓝图 When 干预落地 Then 升 v1.2：`:35` 竞态算术改"2min 确认+10s"并重述 fetch 几乎必胜、`:75` 粒度注"默认 6"→24、`:89` Rollout 改 ≈130-135s/增量 +90s；修订记录补授权行（对齐 failure-forensics v2 先例）+ 记录 +13 行锚点漂移；20s 事故数据标注"待 watchdog 日志重推导"（不删除、不回退 24）——**文档，人工核对**（沿 AC-8 先例） — seam: `docs/intent-blueprints/watchdog-hardening-v1.blueprint.md` 文本 (catches: 蓝图内部自洽; misses: 代码行为——由 AC-2/AC-5 覆盖)
- AC-2: Given 任意支持镜像（curl/git 预装与否）When user-data 渲染 Then `yum update -y` 零出现、无守卫的裸 `apt-get update` 零出现；`ensure_cmd` 守卫形状在档（command -v 前置 + apt/yum 两分支 + `--no-install-recommends`）；wget 零安装 — seam: `templates/user-data.sh` 渲染文本 (catches: 包操作极简形状; misses: 运行时网络行为)
- AC-3: Given apt 族镜像 When 渲染 Then 禁用块位于 apt 守卫内、echo 仅 apt 路径打印且如实；Given yum 族镜像 Then 块整体不执行且无横幅 — seam: 渲染文本守卫形状 (catches: 分支守卫与横幅诚实性; misses: 单元实际存在性——`|| true` 容忍)
- AC-4: Given `runner_version` input 显式非空 Then 原样透传；Given 未设（**action.yml 无 default，空路径可达**）Then resolve 步骤于 proxy env（三键）内以 HEAD 重定向剥 tag 输出 version；Given 探测失败 Then `::warning::` + 输出 fallback 常量；Given 全仓 Then 固定版本号字面量仅余 `RUNNER_FALLBACK_VERSION` 常量单一豁免位（action.yml input default / 模板兜底 / generate-user-data.sh sed 三处清零）；模板含空 `RUNNER_VERSION` 响亮退出守卫；generator sed 模式与模板新默认行锁定同步 — seam: `action.yml` resolve 步骤块 + `steps.runner-version.outputs.version` 消费 + 注入契约测试 (catches: 三层语义与 proxy 接线与三处钉扎清零; misses: GitHub 端真实版本值)
- AC-5: Given `watchdog_stop_window_seconds` 未设 Then 模板不写 /etc/environment 键、watchdog 默认 24；Given 设为 N(正整数) Then trap 后校验前锚定写入 `STOP_CONFIRMATIONS_REQUIRED=<ceil(N/5)>`；非法 N → 响亮非零退出；action 写入行覆盖镜像预置同键值 — seam: `action.yml` input + 渲染文本锚定行 (catches: input→generator→模板→校验→watchdog 全链; misses: 实例运行时时序)
- AC-6: Given 文档面 When 干预落地 Then：README.md/README.cn.md 双语（.cursor 04-readme-sync）各覆盖——`:435` 停止确认窗 prose 改 24/2min、`watchdog_stop_window_seconds` 新行（含 "max seconds of continuous inactivity" 措辞）、`runner_version` 行改 auto-latest 语义、`runner_wait_timeout` 行改 420；action.yml 两 input description 同步；smoke-test 显式 420 传参与 :76-78 过时注释移除 — seam: `README.md`/`README.cn.md`/`action.yml` input 描述 (catches: 文档-行为一致; misses: 调用方覆盖行为)
- AC-7: Given AC-2..6 When RED phase Then 下述映射测试全部落地，既有测试零回归（基线 61 passed，2026-09-17 master 实测，/tmp/pr-review/det-checks.log 在档；本干预不删不弱任何既有断言，注入契约测试为**锁定同步更新**非削弱——更新后须对旧模板反向 RED） — seam: `tests/` 收集集 (catches: 钉扎存在性与零回归; misses: 语义强度——由外环审查)
- AC-8: Given docs/postmortem/2026-09-03-runner-shutdown-incident-review.md When 干预落地 Then `:74` "默认 6 × 5s = 30s"处加 superseded-by-v1.2 注、20s 数据标注与 AC-1 同步、`:47` 排除算术的 `runner_wait_timeout=120s` 前提补 420 改注——**文档，人工核对** — seam: postmortem 文本 (catches: 叙事与 v1.2 一致; misses: 无)
- AC-9: Given CHANGELOG.md When 干预落地 Then [Unreleased] 下按决策 10 分类落三条目（Added/Changed×2 归并陈述）——**文档，人工核对** — seam: CHANGELOG.md (catches: 对调用方可见变更全披露; misses: 无)

## Non-Functional Requirements (NFR)

- NFR-1: dead-man switch 本地约束不破：禁用块与窗口逻辑零新增网络依赖；resolve 步骤一次 HEAD、`--connect-timeout 5 --max-time 15`、失败降级响亮且不阻塞 bootstrap。
- NFR-2: L1 红线：20s 数据**标注**而非删除；24 维持是保守论证而非 hardcode-to-green；无任何"删测试保绿"（注入契约测试的更新须双向 RED 佐证）。
- NFR-3: 接口向后兼容：`runner_version` 显式钉扎者行为不变；`watchdog_stop_window_seconds` 缺省即 PR#2 行为。

## Acceptance-Criteria -> Test Mapping

- AC-2 -> test_no_bulk_update_at_bootstrap
- AC-2 -> test_ensure_cmd_guarded_install_shape
- AC-3 -> test_unattended_disable_apt_guarded_and_pinned
- AC-4 -> test_runner_version_resolve_step_wiring
- AC-4 -> test_no_pinned_runner_version_literals
- AC-5 -> test_watchdog_window_input_plumbing
- AC-6 -> test_readme_stop_window_docs_synced
- AC-7 -> test_generate_user_data_injection_contract

## 用例粒度注（非映射行）

- 结构测试沿用 tests/test_user_data_structure.py（模板断言）与 tests/test_action_workflow.py（action.yml 行窗断言）既有风格；`test_no_pinned_runner_version_literals` 反向扫描**三处**（action.yml input default、模板兜底、generate-user-data.sh sed），显式豁免 `RUNNER_FALLBACK_VERSION` 常量声明行。
- `test_generate_user_data_injection_contract`（既有，更新）：注入集新增 `WATCHDOG_STOP_WINDOW_SECONDS`；`RUNNER_VERSION` 断言随 sed 模式锁定同步更新，且**空值注入 → 渲染产物含响亮退出守卫触发**；更新后对基线前模板反向 RED。
- `test_watchdog_window_input_plumbing` 须覆盖决策 9 全链（含 trap 后/校验前位置锚、ceil 算术、非法 N 响亮、镜像预置值被覆盖语义）。
- AC-1 / AC-8 / AC-9 无自动化测试（文档，人工核对——沿 watchdog-hardening AC-8 先例）。

## Rollout 验证（实施后）

- smoke-test 默认路径断言 resolve 输出为非固定版本值（auto 生效的直接证据）；月度 cron 持续覆盖。
- 成功路径 teardown 维持 ≈130-135s（语义限制已在 README 注明；缩短依赖 follow-up 蓝图 watchdog-fast-teardown-v1）。
- 观察项：fallback 常量与 latest 的漂移幅度（CHANGELOG 纪律的实效性输入）。

## 范围外（显式）

- `watchdog-fast-teardown-v1`：ACTIONS_RUNNER_HOOK_JOB_COMPLETED 标志文件 + watchdog 短路（"执行完即跳出"的完整实现）。
- `BOOTSTRAP_WATCH_TIMEOUT` input 化（1800s 维持，挂 issue）。
- alinux/yum 族镜像的一手实测（本轮探针两败于镜像查询；机制结论不依赖，见背景）。
