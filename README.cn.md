# Setup Aliyun ECS Spot Runner

GitHub Action 用于在阿里云 ECS Spot 实例上创建和设置 self-hosted runner。

## 功能特性

- 动态选择最优 Spot 实例
- 自动创建 ECS Spot 实例
- 自动安装和配置 GitHub Actions Runner
- 支持 Ephemeral Runner 模式（任务完成后自动清理）
- 支持实例自毁机制（Runner 退出后自动删除实例）
- 支持 AMD64 和 ARM64 架构
- 支持代理配置
- 失败时自动清理实例

## 使用方法

### 基本示例

```yaml
name: Build with Spot Runner

on:
  workflow_dispatch:

jobs:
  setup:
    name: Setup Spot Instance
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: write
    outputs:
      instance_id: ${{ steps.setup-runner.outputs.instance_id }}
      runner_name: ${{ steps.setup-runner.outputs.runner_name }}
      runner_online: ${{ steps.setup-runner.outputs.runner_online }}
      cpu_cores: ${{ steps.setup-runner.outputs.cpu_cores }}
    steps:
      - name: Setup Aliyun ECS Spot Runner
        id: setup-runner
        uses: dianplus/cloud-instance-github-runner@master
        with:
          aliyun_access_key_id: ${{ secrets.ALIYUN_ACCESS_KEY_ID }}
          aliyun_access_key_secret: ${{ secrets.ALIYUN_ACCESS_KEY_SECRET }}
          aliyun_region_id: ${{ vars.ALIYUN_REGION_ID }}
          aliyun_vpc_id: ${{ vars.ALIYUN_VPC_ID }}
          aliyun_security_group_id: ${{ vars.ALIYUN_SECURITY_GROUP_ID }}
          aliyun_image_id: ${{ vars.ALIYUN_AMD64_IMAGE_ID }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          arch: amd64
          min_cpu: 8
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}
          vswitch_id_g: ${{ vars.ALIYUN_VSWITCH_ID_G }}

  build:
    name: Build
    needs: setup
    runs-on: [self-hosted, Linux, aliyun, spot-instance]
    if: needs.setup.outputs.runner_online == 'true'
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Build
        run: |
          echo "Building on runner: ${{ needs.setup.outputs.runner_name }}"
          echo "CPU cores: ${{ needs.setup.outputs.cpu_cores }}"
```

### 多架构示例

在同一个 workflow 中为不同架构创建 runner 时，可以使用架构特定的镜像族：

```yaml
name: Build with Multi-Arch Spot Runners

on:
  workflow_dispatch:

jobs:
  setup-amd64:
    name: Setup AMD64 Spot Instance
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: write
    steps:
      - name: Setup Aliyun ECS Spot Runner
        uses: dianplus/cloud-instance-github-runner@master
        with:
          aliyun_access_key_id: ${{ secrets.ALIYUN_ACCESS_KEY_ID }}
          aliyun_access_key_secret: ${{ secrets.ALIYUN_ACCESS_KEY_SECRET }}
          aliyun_region_id: ${{ vars.ALIYUN_REGION_ID }}
          aliyun_vpc_id: ${{ vars.ALIYUN_VPC_ID }}
          aliyun_security_group_id: ${{ vars.ALIYUN_SECURITY_GROUP_ID }}
          aliyun_image_family: acs:ubuntu_24_04_x64
          github_token: ${{ secrets.GITHUB_TOKEN }}
          arch: amd64
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}

  setup-arm64:
    name: Setup ARM64 Spot Instance
    runs-on: ubuntu-latest
    permissions:
      contents: read
      actions: write
    steps:
      - name: Setup Aliyun ECS Spot Runner
        uses: dianplus/cloud-instance-github-runner@master
        with:
          aliyun_access_key_id: ${{ secrets.ALIYUN_ACCESS_KEY_ID }}
          aliyun_access_key_secret: ${{ secrets.ALIYUN_ACCESS_KEY_SECRET }}
          aliyun_region_id: ${{ vars.ALIYUN_REGION_ID }}
          aliyun_vpc_id: ${{ vars.ALIYUN_VPC_ID }}
          aliyun_security_group_id: ${{ vars.ALIYUN_SECURITY_GROUP_ID }}
          aliyun_image_family: acs:ubuntu_24_04_arm64
          github_token: ${{ secrets.GITHUB_TOKEN }}
          arch: arm64
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}
```

**注意**：阿里云镜像族名称包含架构信息（例如，AMD64 使用 `acs:ubuntu_24_04_x64`，ARM64 使用 `acs:ubuntu_24_04_arm64`）。您必须确保 `aliyun_image_family` 参数与 `arch` 参数匹配。在同一个 workflow 中为不同架构创建 runner 时，需要为每个架构提供对应的镜像族。

## 输入参数

### 必需参数

| 参数名                     | 描述                                               | 示例                          |
| -------------------------- | -------------------------------------------------- | ----------------------------- |
| `aliyun_access_key_id`     | 阿里云 Access Key ID                               | `LTAI5t...`                   |
| `aliyun_access_key_secret` | 阿里云 Access Key Secret                           | `xxx...`                      |
| `aliyun_region_id`         | 阿里云区域 ID                                      | `cn-hangzhou`                 |
| `aliyun_vpc_id`            | VPC ID                                             | `vpc-xxx`                     |
| `aliyun_security_group_id` | 安全组 ID                                          | `sg-xxx`                      |
| `aliyun_image_id`          | 镜像 ID（如果提供了 `aliyun_image_family` 则可选） | `m-xxx`                       |
| `github_token`             | GitHub Token（用于获取 registration token）        | `${{ secrets.GITHUB_TOKEN }}` |

**重要提示**：`github_token` 用于调用 GitHub API 获取 runner registration token。**注意**：仅配置 workflow 的 `permissions` 是不够的，必须使用预先配置了权限的 PAT (Personal Access Token)。PAT 的权限要求：经典 PAT 需要 `repo` scope，细粒度 PAT 或 GitHub Apps 需要 `actions:write` 权限。详见下方"权限配置"章节。

### 可选参数

| 参数名                               | 描述                                 | 默认值              |
| ------------------------------------ | ------------------------------------ | ------------------- |
| `aliyun_image_family`                | 镜像族系（优先于 `aliyun_image_id`）。必须与 `arch` 参数指定的架构匹配。例如，`amd64` 使用 `acs:ubuntu_24_04_x64`，`arm64` 使用 `acs:ubuntu_24_04_arm64`。可用的镜像族系请参考[阿里云公共镜像文档](https://help.aliyun.com/zh/ecs/user-guide/public-mirroring-overview/)。 | -                   |
| `aliyun_key_pair_name`               | SSH 密钥对名称                       | -                   |
| `aliyun_ecs_self_destruct_role_name` | 实例自毁角色名称                     | -                   |
| `runner_labels`                      | Runner 标签（逗号分隔）              | `self-hosted,Linux,aliyun,spot-instance` |
| `runner_version`                     | GitHub Actions Runner 版本           | `2.311.0`           |
| `arch`                               | 架构（`amd64` 或 `arm64`）           | `amd64`             |
| `min_cpu`                            | 最小 CPU 核心数                      | `8`                 |
| `min_mem`                            | 最小内存 GB（会根据架构自动计算）    | -                   |
| `max_cpu`                            | 最大 CPU 核心数                      | `64`                |
| `max_mem`                            | 最大内存 GB（会根据架构自动计算）    | -                   |
| `http_proxy`                         | HTTP 代理 URL                        | -                   |
| `https_proxy`                        | HTTPS 代理 URL                       | -                   |
| `no_proxy`                           | NO_PROXY 环境变量值                  | -                   |
| `vswitch_id_a` 到 `vswitch_id_z`     | 各可用区的 VSwitch ID                | -                   |

## 输出参数

| 参数名          | 描述                                  |
| --------------- | ------------------------------------- |
| `instance_id`   | 创建的 ECS 实例 ID                    |
| `runner_name`   | Runner 名称                           |
| `runner_online` | Runner 是否成功上线（`true`/`false`） |
| `cpu_cores`     | 实例 CPU 核心数                       |

## 前置条件

### 1. 阿里云资源准备

#### 创建 VPC 和 VSwitches

**强烈建议**：对于 CI/CD 任务，强烈建议创建与生产环境隔离的 VPC 环境！

```bash
# 创建 VPC
aliyun vpc CreateVpc \
  --RegionId ${ALIYUN_REGION_ID} \
  --VpcName vpc-ci-runner \
  --CidrBlock 172.16.0.0/16

# 在多个可用区创建 VSwitches
aliyun vpc CreateVSwitch \
  --RegionId ${ALIYUN_REGION_ID} \
  --VSwitchName vsw-ci-runner-b \
  --VpcId vpc-xxx \
  --CidrBlock 172.16.1.0/24 \
  --ZoneId ${ALIYUN_REGION_ID}-b
```

#### 创建安全组

```bash
aliyun ecs CreateSecurityGroup \
  --RegionId ${ALIYUN_REGION_ID} \
  --GroupName sg-ci-runner \
  --VpcId vpc-xxx \
  --Description "Security group for CI runners"
```

### 2. GitHub Secrets 和 Variables 配置

#### Secrets（敏感信息）

在仓库设置中添加以下 Secrets：

- `ALIYUN_ACCESS_KEY_ID`: 阿里云 Access Key ID
- `ALIYUN_ACCESS_KEY_SECRET`: 阿里云 Access Key Secret

#### Variables（非敏感配置）

在仓库设置中添加以下 Variables：

- `ALIYUN_REGION_ID`: 区域 ID（如 `cn-hangzhou`）
- `ALIYUN_VPC_ID`: VPC ID
- `ALIYUN_SECURITY_GROUP_ID`: 安全组 ID
- `ALIYUN_VSWITCH_ID_A` 到 `ALIYUN_VSWITCH_ID_Z`: 各可用区的 VSwitch ID（根据需要配置）
- `ALIYUN_AMD64_IMAGE_ID`: AMD64 镜像 ID（推荐 Ubuntu 24）
- `ALIYUN_ARM64_IMAGE_ID`: ARM64 镜像 ID（推荐 Ubuntu 24）
- `ALIYUN_KEY_PAIR_NAME`: SSH 密钥对名称（可选）
- `ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME`: 实例自毁角色名称（可选）

### 3. 权限配置

#### GitHub Actions 权限

**重要**：使用本 Action 时，必须提供一个预先配置了权限的 PAT (Personal Access Token) 作为 `github_token`，因为 Action 需要通过 `github_token` 调用 GitHub API 的 `actions.createRegistrationTokenForRepo` 接口来获取 runner registration token。

**注意**：仅配置 workflow 的 `permissions` 是不够的，必须使用具有相应权限的 PAT。

PAT 的权限要求：

- **经典 PAT**：需要 `repo` scope
- **细粒度 PAT 或 GitHub Apps**：需要 `actions:write` 权限，且**必须设置为访问所有仓库（All repositories）**，因为 runner 需要能够为所有仓库创建 registration token

```yaml
permissions:
  contents: read
  actions: write  # 虽然配置了，但实际权限来自 PAT
```

**重要**：即使 workflow 中配置了 `permissions`，如果使用的 `github_token`（PAT）没有相应权限，仍然无法获取 registration token 并会报错。

#### 阿里云 RAM 权限策略

RAM 用户需要以下权限：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:RunInstances",
        "ecs:DescribeInstances",
        "ecs:DescribeImages",
        "ecs:DescribeSecurityGroups",
        "ecs:DescribeAvailableResource",
        "ecs:DescribeSpotPriceHistory"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": ["vpc:DescribeVSwitches", "vpc:DescribeVpcs"],
      "Resource": "*"
    }
  ]
}
```

#### 实例自毁角色（可选）

如果启用实例自毁功能，需要创建 ECS 实例角色并授予删除实例的权限。实例自毁机制允许 Runner 任务完成后自动删除 ECS 实例，避免资源浪费。

##### 创建 RAM 角色

1. **登录 RAM 控制台**
   - 访问 [RAM 控制台](https://ram.console.aliyun.com/)
   - 在左侧导航栏选择"身份管理" > "角色"

2. **创建角色**

   ```bash
   # 使用阿里云 CLI 创建角色
   aliyun ram CreateRole \
     --RoleName EcsSelfDestructRole \
     --AssumeRolePolicyDocument '{
       "Statement": [{
         "Action": "sts:AssumeRole",
         "Effect": "Allow",
         "Principal": {
           "Service": ["ecs.aliyuncs.com"]
         }
       }],
       "Version": "1"
     }'
   ```

   或通过控制台创建：
   - 单击"创建角色"
   - 选择"阿里云服务"作为可信实体类型
   - 选择"云服务器ECS"作为受信服务
   - 设置角色名称（如 `EcsSelfDestructRole`）
   - 完成创建

##### 为角色授予删除实例权限

###### 推荐方式：使用最小权限策略

创建自定义策略，仅授予删除实例的权限：

```bash
# 创建自定义策略
aliyun ram CreatePolicy \
  --PolicyName EcsSelfDestructPolicy \
  --PolicyDocument '{
    "Version": "1",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "ecs:DeleteInstance",
        "ecs:DescribeInstances"
      ],
      "Resource": "*"
    }]
  }'

# 为角色授权
aliyun ram AttachPolicyToRole \
  --PolicyType Custom \
  --PolicyName EcsSelfDestructPolicy \
  --RoleName EcsSelfDestructRole
```

**或使用控制台授权：**

- 在角色详情页面，单击"添加权限"
- 搜索并选择自定义策略 `EcsSelfDestructPolicy`（或使用 `AliyunECSFullAccess` 完整权限，不推荐）
- 完成授权

##### 配置到 GitHub Variables

在 GitHub 仓库设置中添加 Variable：

- `ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME`: 设置为创建的角色名称（如 `EcsSelfDestructRole`）

##### 实例自毁工作原理

1. **角色绑定**：创建 ECS 实例时，通过 `--RamRoleName` 参数将角色附加到实例
2. **自毁脚本**：实例启动时，User Data 脚本会在 `/usr/local/bin/self-destruct.sh` 创建自毁脚本
3. **权限获取**：自毁脚本通过实例元数据服务获取角色临时凭证：

   ```bash
   curl http://100.100.100.200/latest/meta-data/ram/security-credentials/EcsSelfDestructRole
   ```

4. **自动删除**：Runner 任务完成后，通过 post-job hook 或 systemd 服务执行自毁脚本，使用角色权限调用 `DeleteInstance` API 删除实例

##### 验证配置

- 检查实例日志：`/var/log/user-data.log` 应显示角色配置信息
- 检查自毁日志：`/var/log/self-destruct.log` 记录删除过程
- 测试：创建测试实例，等待 Runner 完成任务后验证实例是否自动删除

## 架构说明

### AMD64 架构

- CPU:RAM = 1:1 比例
- 默认范围：8c8g 到 64c64g
- 无实例规格族限制

### ARM64 架构

- CPU:RAM = 1:2 比例
- 默认范围：8c16g 到 64c128g
- 实际上限制为 `ecs.c8y` 和 `ecs.c8r` 实例族

## 工作原理

1. **选择最优实例**：使用 `spot-instance-advisor` 工具查询价格最优的 Spot 实例
2. **创建实例**：调用阿里云 API 创建 ECS Spot 实例，传递 User Data 脚本
3. **配置 Runner**：实例启动时自动执行 User Data 脚本，安装和配置 GitHub Actions Runner
4. **等待上线**：轮询检查 Runner 是否成功注册并上线
5. **自动清理**：Runner 任务完成后自动删除实例（通过 post-job hook 或 systemd service）

## 故障排查

### Runner 未上线

- 检查实例是否成功创建
- 查看实例日志：`/var/log/user-data.log`
- 检查 Runner 服务状态：`systemctl status actions.runner.*.service`

### 实例创建失败

- 检查 VSwitch ID 是否正确配置
- 检查安全组规则是否允许必要流量
- 检查镜像 ID 是否有效
- 查看错误日志中的具体错误信息

### 实例未自动删除

- 检查实例角色是否正确配置
- 查看自毁日志：`/var/log/self-destruct.log`
- 检查 post-job hook 是否正常执行

## License

MIT
