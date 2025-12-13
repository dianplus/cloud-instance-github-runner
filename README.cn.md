# Setup Aliyun ECS Spot Runner

GitHub Action 用于在阿里云 ECS Spot 实例上创建和设置 self-hosted runner。

## 功能特性

- 动态选择最优 Spot 实例
- 支持指定精确实例规格（绕过 CPU/内存/架构选择）
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
          aliyun_region_id: "cn-hangzhou"
          aliyun_vpc_id: ${{ vars.ALIYUN_VPC_ID }}
          aliyun_security_group_id: ${{ vars.ALIYUN_SECURITY_GROUP_ID }}
          aliyun_image_family: "acs:ubuntu_24_04_arm64"
          aliyun_ecs_self_destruct_role_name: "GitHubRunnerSelfDestructRole"
          aliyun_key_pair_name: ${{ secrets.ALIYUN_KEY_PAIR_NAME }}
          github_token: ${{ secrets.RUNNER_REGISTRATION_PAT }}
          arch: arm64
          min_cpu: 8
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}
          vswitch_id_g: ${{ vars.ALIYUN_VSWITCH_ID_G }}
          vswitch_id_h: ${{ vars.ALIYUN_VSWITCH_ID_H }}
          vswitch_id_i: ${{ vars.ALIYUN_VSWITCH_ID_I }}
          vswitch_id_j: ${{ vars.ALIYUN_VSWITCH_ID_J }}
          vswitch_id_k: ${{ vars.ALIYUN_VSWITCH_ID_K }}
          http_proxy: ${{ vars.HTTP_PROXY }}
          https_proxy: ${{ vars.HTTPS_PROXY }}
          no_proxy: ${{ vars.NO_PROXY }}

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
    # permissions 配置是可选的，因为本 Action 使用 PAT 而非 GITHUB_TOKEN
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
          github_token: ${{ secrets.RUNNER_REGISTRATION_PAT }}
          arch: amd64
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}

  setup-arm64:
    name: Setup ARM64 Spot Instance
    runs-on: ubuntu-latest
    # permissions 配置是可选的，因为本 Action 使用 PAT 而非 GITHUB_TOKEN
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
          github_token: ${{ secrets.RUNNER_REGISTRATION_PAT }}
          arch: arm64
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}
```

**注意**：确保 `aliyun_image_family` 与 `arch` 参数匹配（AMD64: `acs:ubuntu_24_04_x64`，ARM64: `acs:ubuntu_24_04_arm64`）。

### 指定实例规格示例

当需要使用特定实例规格时，可以使用 `aliyun_instance_type` 参数：

```yaml
name: Build with Specific Instance Type

on:
  workflow_dispatch:

jobs:
  setup:
    name: Setup Spot Instance with Specific Type
    runs-on: ubuntu-latest
    steps:
      - name: Setup Aliyun ECS Spot Runner
        uses: dianplus/cloud-instance-github-runner@master
        with:
          aliyun_access_key_id: ${{ secrets.ALIYUN_ACCESS_KEY_ID }}
          aliyun_access_key_secret: ${{ secrets.ALIYUN_ACCESS_KEY_SECRET }}
          aliyun_region_id: "cn-hangzhou"
          aliyun_vpc_id: ${{ vars.ALIYUN_VPC_ID }}
          aliyun_security_group_id: ${{ vars.ALIYUN_SECURITY_GROUP_ID }}
          aliyun_image_family: "acs:ubuntu_24_04_x64"
          github_token: ${{ secrets.RUNNER_REGISTRATION_PAT }}
          aliyun_instance_type: "ecs.c7.2xlarge"
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}
          vswitch_id_g: ${{ vars.ALIYUN_VSWITCH_ID_G }}
```

**注意**：当提供 `aliyun_instance_type` 参数时，`min_cpu`、`max_cpu`、`min_mem`、`max_mem` 和 `arch` 参数将被忽略。Action 将查询指定实例规格在所有可用区的 spot 价格。

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
| `github_token`             | GitHub Token（用于获取 registration token）        | `${{ secrets.RUNNER_REGISTRATION_PAT }}` |

**重要**：`github_token` 必须是具有相应权限的 PAT，详见下方"权限配置"章节。

### 可选参数

| 参数名                               | 描述                                 | 默认值              |
| ------------------------------------ | ------------------------------------ | ------------------- |
| `aliyun_image_family`                | 镜像族系（优先于 `aliyun_image_id`）。必须与 `arch` 参数指定的架构匹配。例如，`amd64` 使用 `acs:ubuntu_24_04_x64`，`arm64` 使用 `acs:ubuntu_24_04_arm64`。可用的镜像族系请参考[阿里云公共镜像文档](https://help.aliyun.com/zh/ecs/user-guide/public-mirroring-overview/)。 | -                   |
| `aliyun_key_pair_name`               | SSH 密钥对名称                       | -                   |
| `aliyun_ecs_self_destruct_role_name` | 实例自毁角色名称                     | -                   |
| `runner_labels`                      | Runner 标签（逗号分隔）              | `self-hosted,Linux,aliyun,spot-instance` |
| `runner_version`                     | GitHub Actions Runner 版本           | `2.311.0`           |
| `aliyun_instance_type`               | 指定实例规格（如 `ecs.c7.2xlarge`）。提供此参数时，将忽略 `min_cpu`/`max_cpu`/`min_mem`/`max_mem`/`arch` 参数，并查询该精确规格的 spot 价格。仅允许单个值。 | -                   |
| `arch`                               | 架构（`amd64` 或 `arm64`）           | `amd64`             |
| `min_cpu`                            | 最小 CPU 核心数                      | `8`                 |
| `min_mem`                            | 最小内存 GB（会根据架构自动计算）    | -                   |
| `max_cpu`                            | 最大 CPU 核心数                      | `64`                |
| `max_mem`                            | 最大内存 GB（会根据架构自动计算）    | -                   |
| `http_proxy`                         | HTTP 代理 URL                        | -                   |
| `https_proxy`                        | HTTPS 代理 URL                       | -                   |
| `no_proxy`                           | NO_PROXY 环境变量值                  | -                   |
| `vswitch_id_a` 到 `vswitch_id_z`     | 各可用区的 VSwitch ID                | -                   |

**代理配置（中国大陆区域）**：使用中国大陆区域的 ECS 实例时，强烈建议配置代理以访问 GitHub。

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

建议为 CI/CD 创建独立的 VPC 环境。

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

本 Action 使用 PAT 生成 registration token，而非 `GITHUB_TOKEN`。workflow 的 `permissions` 配置对获取 registration token 不适用。

PAT 权限要求：

- **经典 PAT**：`repo` scope
- **细粒度 PAT 或 GitHub Apps**：
  - 访问范围：仅限运行本 action 的仓库
  - 权限：**Administration: Read and write**（仓库级别，非组织级别）
  - 设置合理的过期时间

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
      "Action": [
        "vpc:DescribeVSwitches",
        "vpc:DescribeVpcs"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "ram:PassRole",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecs:DeleteInstance",
        "ecs:DeleteInstances"
      ],
      "Resource": "acs:ecs:*:*:instance/*",
      "Condition": {
        "StringEquals": {
          "acs:ResourceTag/GITHUB_RUNNER_TYPE": [
            "aliyun-ecs-spot"
          ]
        }
      }
    }
  ]
}
```

如果还希望创建自定义镜像以缩短 CI 时间，那么还需要以下权限：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:CreateImage",
        "ecs:DescribeImages",
        "ecs:ModifyImageAttribute",
        "ecs:DeleteImage",
        "ecs:DescribeImageFromFamily"
      ],
      "Resource": "*"
    }
  ]
}
```

#### 实例自毁角色（可选）

启用实例自毁功能需要创建 ECS 实例角色并授予删除实例权限。

**创建 RAM 角色：**

```bash
aliyun ram CreateRole \
  --RoleName GitHubRunnerSelfDestructRole \
  --AssumeRolePolicyDocument '{
    "Statement": [{
      "Action": "sts:AssumeRole",
      "Effect": "Allow",
      "Principal": {"Service": ["ecs.aliyuncs.com"]}
    }],
    "Version": "1"
  }'
```

**创建并授权策略：**

```bash
aliyun ram CreatePolicy \
  --PolicyName EcsSelfDestructPolicy \
  --PolicyDocument '{
    "Version": "1",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["ecs:DeleteInstance", "ecs:DescribeInstances"],
      "Resource": "*",
      "Condition": {"StringEquals": {"acs:ResourceTag/GITHUB_RUNNER_TYPE": ["aliyun-ecs-spot"]}}
    }]
  }'

aliyun ram AttachPolicyToRole \
  --PolicyType Custom \
  --PolicyName EcsSelfDestructPolicy \
  --RoleName GitHubRunnerSelfDestructRole
```

**配置 GitHub Variable：**

- `ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME`: 角色名称（如 `GitHubRunnerSelfDestructRole`）

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

1. 使用 `spot-instance-advisor` 选择最优 Spot 实例（如果提供了 `aliyun_instance_type`，则查询指定实例规格的 spot 价格）
2. 创建 ECS Spot 实例并传递 User Data 脚本
3. 实例启动时自动安装配置 GitHub Actions Runner
4. 等待 Runner 注册上线
5. 任务完成后自动删除实例

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
