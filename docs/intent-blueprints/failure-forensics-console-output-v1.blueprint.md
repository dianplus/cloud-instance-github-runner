---
blueprint_version: v1
frozen_at: 2026-08-21
task: failure-forensics-console-output
status: frozen
---

# Intent Blueprint: 失败取证——销毁前抢救实例控制台日志

## Background

wait-runner 超时/创建失败后清理步骤会销毁实例，实例内 user-data/cloud-init 日志随之蒸发——原泄漏事故与冒烟调试均只能靠外部推断实例内发生过什么。阿里云 `GetInstanceConsoleOutput` 可在删除前取得实例最近一次启动的系统控制台输出（含 cloud-init 日志；Base64 编码；仅 Linux——本 action 的 runner 全部为 Linux；实例删除后不可得）。已对官方 API 文档核验（help.aliyun.com，2026-08-21）。

## Core Use Cases

- UC-1: action 失败清理时，在销毁实例前 best-effort 抓取其控制台日志并归档为 workflow artifact——"装不上"类事故从"猜"变为"日志在手"。

## 设计决策（显式声明，防误改）

- **取证是 best-effort，计费安全优先**：fetch 的任何失败（CLI 缺失/API 错误/实例已消失/解码失败）只产生 stderr 警告并 exit 0，绝不阻断后续 cleanup-instance.sh 的销毁。这与 cleanup-instance.sh 的"响亮失败"语义相反，是刻意差异：清理失败=泄漏风险，取证失败=少一份日志。

## Acceptance Criteria

- AC-1: `scripts/fetch-console-output.sh`：读取既有环境约定（ALIYUN_ACCESS_KEY_ID/SECRET/REGION_ID、INSTANCE_ID、CONSOLE_LOG_FILE 默认 `/tmp/instance-console.log`）。成功路径：导出 ALIBABA_CLOUD_* → `aliyun ecs GetInstanceConsoleOutput --RegionId .. --InstanceId ..` → 从 JSON 提取 ConsoleOutput（python3 json 解析，禁 jq）→ base64 解码写入 CONSOLE_LOG_FILE → stdout 报告行数 → exit 0。失败路径（命令失败/CLI 缺失/JSON 或 base64 解析失败）：stderr `Warning: ...` → exit 0，不产生半写文件（先写临时文件再原子 mv，或失败即删）。
- AC-2: fetch 脚本不得含 `command -v aliyun` 硬失败预检、不得 exit 非零（best-effort 契约的显式反向断言）。
- AC-3: action.yml Cleanup on Failure 步骤内，fetch-console-output.sh 的调用必须位于 cleanup-instance.sh 之前（console 输出仅存活至删除前）。
- AC-4: action.yml 新增 console 日志 artifact 上传步骤：`uses: actions/upload-artifact@v4`，`if: failure() || cancelled()`，`with.path` 指向 CONSOLE_LOG_FILE 同路径，`if-no-files-found: ignore`（成功路径与取证失败均不得产生空 artifact 报错），name 含 instance id 可辨识。
- AC-5: tests conftest 的 aliyun stub 扩展 `GetInstanceConsoleOutput` 子命令：`console_b64` marker 文件内容为 base64 载荷（脚本解码后应等于明文）；默认无 marker 时该子命令 rc=1 stderr 模拟错误。由 AC-1 测试复用，无独立测试（如实标注）。

## Non-Functional Requirements

- NFR-1: 不新增依赖（python3/base64 为既有依赖面）。
- NFR-2: `bash -n` 零语法错误；ruff 干净（不涉及 py 改动）。
- NFR-3: 测试零网络零凭证；CONSOLE_LOG_FILE 在测试中指向 tmp_path。

## Non-Goals

- 不修改 cleanup-instance.sh 本体及其"响亮失败"语义。
- 不支持 Windows 实例（API 限制）。
- 不做日志截断/脱敏（artifact 为仓库私有）。
- 不在本蓝图内扩展冒烟 workflow（后续可选）。

## Acceptance-Criteria -> Test Mapping

- AC-1 → tests/test_fetch_console_output.py::test_fetch_decodes_console_output_to_file
- AC-1/AC-2 → tests/test_fetch_console_output.py::test_fetch_forensic_failures_never_block_cleanup
- AC-3/AC-4 → tests/test_action_workflow.py::test_cleanup_captures_console_output_before_deletion
