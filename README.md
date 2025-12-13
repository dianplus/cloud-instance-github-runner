# Setup Aliyun ECS Spot Runner

GitHub Action for creating and setting up a self-hosted runner on Aliyun ECS Spot instances.

## Features

- Dynamic selection of optimal Spot instances
- Support for specifying exact instance type (bypasses CPU/memory/arch selection)
- Automatic ECS Spot instance creation
- Automatic installation and configuration of GitHub Actions Runner
- Support for Ephemeral Runner mode (automatic cleanup after task completion)
- Support for instance self-destruct mechanism (automatic instance deletion after Runner exits)
- Support for AMD64 and ARM64 architectures
- Support for proxy configuration
- Automatic instance cleanup on failure

## Usage

### Basic Example

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

### Multi-Architecture Example

When creating runners for different architectures in the same workflow, you can use architecture-specific image families:

```yaml
name: Build with Multi-Arch Spot Runners

on:
  workflow_dispatch:

jobs:
  setup-amd64:
    name: Setup AMD64 Spot Instance
    runs-on: ubuntu-latest
    # permissions configuration is optional since this Action uses PAT instead of GITHUB_TOKEN
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
    # permissions configuration is optional since this Action uses PAT instead of GITHUB_TOKEN
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

**Note**: Ensure `aliyun_image_family` matches `arch` (AMD64: `acs:ubuntu_24_04_x64`, ARM64: `acs:ubuntu_24_04_arm64`).

### Specify Instance Type Example

When you need to use a specific instance type, you can use the `aliyun_instance_type` parameter:

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

**Note**: When `aliyun_instance_type` is provided, the `min_cpu`, `max_cpu`, `min_mem`, `max_mem`, and `arch` parameters are ignored. The action will query spot prices for the specified instance type across all availability zones.

## Input Parameters

### Required Parameters

| Parameter                  | Description                                              | Example                       |
| -------------------------- | -------------------------------------------------------- | ----------------------------- |
| `aliyun_access_key_id`     | Aliyun Access Key ID                                     | `LTAI5t...`                   |
| `aliyun_access_key_secret` | Aliyun Access Key Secret                                 | `xxx...`                      |
| `aliyun_region_id`         | Aliyun Region ID                                         | `cn-hangzhou`                 |
| `aliyun_vpc_id`            | VPC ID                                                   | `vpc-xxx`                     |
| `aliyun_security_group_id` | Security Group ID                                        | `sg-xxx`                      |
| `aliyun_image_id`          | Image ID (optional if `aliyun_image_family` is provided) | `m-xxx`                       |
| `github_token`             | GitHub Token (for getting registration token)            | `${{ secrets.RUNNER_REGISTRATION_PAT }}` |

**Important**: `github_token` must be a PAT with appropriate permissions. See "Permission Configuration" below.

### Optional Parameters

| Parameter                            | Description                                            | Default             |
| ------------------------------------ | ------------------------------------------------------ | ------------------- |
| `aliyun_image_family`                | Image Family (takes precedence over `aliyun_image_id`). Must match the architecture specified in `arch` parameter. For example, use `acs:ubuntu_24_04_x64` for `amd64`, `acs:ubuntu_24_04_arm64` for `arm64`. See [Aliyun public image documentation](https://help.aliyun.com/zh/ecs/user-guide/public-mirroring-overview/) for available image families. | -                   |
| `aliyun_key_pair_name`               | SSH Key Pair Name                                      | -                   |
| `aliyun_ecs_self_destruct_role_name` | Instance Self-Destruct Role Name                       | -                   |
| `runner_labels`                      | Runner labels (comma-separated)                        | `self-hosted,Linux,aliyun,spot-instance` |
| `runner_version`                     | GitHub Actions Runner version                          | `2.311.0`           |
| `aliyun_instance_type`               | Specific instance type (e.g., `ecs.c7.2xlarge`). When provided, ignores `min_cpu`/`max_cpu`/`min_mem`/`max_mem`/`arch` and queries spot price for this exact type. Only single value allowed. | -                   |
| `arch`                               | Architecture (`amd64` or `arm64`)                      | `amd64`             |
| `min_cpu`                            | Minimum CPU cores                                      | `8`                 |
| `min_mem`                            | Minimum memory in GB (auto-calculated if not provided) | -                   |
| `max_cpu`                            | Maximum CPU cores                                      | `64`                |
| `max_mem`                            | Maximum memory in GB (auto-calculated if not provided) | -                   |
| `http_proxy`                         | HTTP Proxy URL                                         | -                   |
| `https_proxy`                        | HTTPS Proxy URL                                        | -                   |
| `no_proxy`                           | NO_PROXY environment variable value                    | -                   |
| `vswitch_id_a` to `vswitch_id_z`     | VSwitch IDs for each availability zone                 | -                   |

**Proxy Configuration (Mainland China Regions)**: Strongly recommended when using ECS instances in Mainland China regions.

## Output Parameters

| Parameter       | Description                               |
| --------------- | ----------------------------------------- |
| `instance_id`   | Created ECS instance ID                   |
| `runner_name`   | Runner name                               |
| `runner_online` | Whether runner is online (`true`/`false`) |
| `cpu_cores`     | Instance CPU cores                        |

## Prerequisites

### 1. Aliyun Resource Preparation

#### Create VPC and VSwitches

Recommended to create a separate VPC for CI/CD.

```bash
# Create VPC
aliyun vpc CreateVpc \
  --RegionId ${ALIYUN_REGION_ID} \
  --VpcName vpc-ci-runner \
  --CidrBlock 172.16.0.0/16

# Create VSwitches in multiple availability zones
aliyun vpc CreateVSwitch \
  --RegionId ${ALIYUN_REGION_ID} \
  --VSwitchName vsw-ci-runner-b \
  --VpcId vpc-xxx \
  --CidrBlock 172.16.1.0/24 \
  --ZoneId ${ALIYUN_REGION_ID}-b
```

#### Create Security Group

```bash
aliyun ecs CreateSecurityGroup \
  --RegionId ${ALIYUN_REGION_ID} \
  --GroupName sg-ci-runner \
  --VpcId vpc-xxx \
  --Description "Security group for CI runners"
```

### 2. GitHub Secrets and Variables Configuration

#### Secrets (Sensitive Information)

Add the following Secrets in repository settings:

- `ALIYUN_ACCESS_KEY_ID`: Aliyun Access Key ID
- `ALIYUN_ACCESS_KEY_SECRET`: Aliyun Access Key Secret

#### Variables (Non-sensitive Configuration)

Add the following Variables in repository settings:

- `ALIYUN_REGION_ID`: Region ID (e.g., `cn-hangzhou`)
- `ALIYUN_VPC_ID`: VPC ID
- `ALIYUN_SECURITY_GROUP_ID`: Security Group ID
- `ALIYUN_VSWITCH_ID_A` to `ALIYUN_VSWITCH_ID_Z`: VSwitch IDs for each availability zone (configure as needed)
- `ALIYUN_AMD64_IMAGE_ID`: AMD64 Image ID (recommended: Ubuntu 24)
- `ALIYUN_ARM64_IMAGE_ID`: ARM64 Image ID (recommended: Ubuntu 24)
- `ALIYUN_KEY_PAIR_NAME`: SSH Key Pair Name (optional)
- `ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME`: Instance Self-Destruct Role Name (optional)

### 3. Permission Configuration

#### GitHub Actions Permissions

This Action uses PAT to generate registration token, not `GITHUB_TOKEN`. Workflow `permissions` configuration does not apply.

PAT permission requirements:

- **Classic PAT**: `repo` scope
- **Fine-grained PAT or GitHub Apps**:
  - Access: Only repositories where this action will run
  - Permissions: **Administration: Read and write** (repository-level, not organization-level)
  - Set a reasonable expiration time

#### Aliyun RAM Permission Policy

RAM user needs the following permissions:

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

#### Instance Self-Destruct Role (Optional)

Create an ECS instance role with instance deletion permissions to enable self-destruct.

**Create RAM Role:**

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

**Create and attach policy:**

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

**Configure GitHub Variable:**

- `ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME`: Role name (e.g., `GitHubRunnerSelfDestructRole`)

If you also want to create custom images to shorten CI time, you need the following additional permissions:

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

## Architecture Notes

### AMD64 Architecture

- CPU:RAM = 1:1 ratio
- Default range: 8c8g to 64c64g
- No instance family restrictions

### ARM64 Architecture

- CPU:RAM = 1:2 ratio
- Default range: 8c16g to 64c128g
- Actually limited to `ecs.c8y` and `ecs.c8r` instance families

## How It Works

1. Use `spot-instance-advisor` to select optimal Spot instance (or query spot price for a specific instance type if `aliyun_instance_type` is provided)
2. Create ECS Spot instance with User Data script
3. Instance automatically installs and configures GitHub Actions Runner on startup
4. Wait for Runner to register and come online
5. Automatically delete instance after task completion

## Troubleshooting

### Runner Not Coming Online

- Check if instance was created successfully
- View instance logs: `/var/log/user-data.log`
- Check Runner service status: `systemctl status actions.runner.*.service`

### Instance Creation Failed

- Check if VSwitch IDs are correctly configured
- Check if security group rules allow necessary traffic
- Check if image ID is valid
- View specific error messages in error logs

### Instance Not Auto-Deleted

- Check if instance role is correctly configured
- View self-destruct logs: `/var/log/self-destruct.log`
- Check if post-job hook is executing normally

## License

MIT
