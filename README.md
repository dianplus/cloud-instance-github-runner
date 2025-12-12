# Setup Aliyun ECS Spot Runner

GitHub Action for creating and setting up a self-hosted runner on Aliyun ECS Spot instances.

## Features

- Dynamic selection of optimal Spot instances
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
          github_token: ${{ secrets.RUNNER_REGISTRATION_PAT }}
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
          github_token: ${{ secrets.RUNNER_REGISTRATION_PAT }}
          arch: arm64
          vswitch_id_b: ${{ vars.ALIYUN_VSWITCH_ID_B }}
```

**Note**: Aliyun image family names include architecture information (e.g., `acs:ubuntu_24_04_x64` for AMD64, `acs:ubuntu_24_04_arm64` for ARM64). You must ensure that the `aliyun_image_family` parameter matches the `arch` parameter. When creating runners for different architectures in the same workflow, provide the corresponding image family for each architecture.

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

**Important**: The `github_token` is used to call GitHub API to get runner registration token. **Note**: Simply configuring workflow's `permissions` is not sufficient. You must use a pre-configured PAT (Personal Access Token) with appropriate permissions. PAT permission requirements: Classic PATs require `repo` scope, while fine-grained PATs or GitHub Apps require `actions:write` permission. See the "Permission Configuration" section below for details.

### Optional Parameters

| Parameter                            | Description                                            | Default             |
| ------------------------------------ | ------------------------------------------------------ | ------------------- |
| `aliyun_image_family`                | Image Family (takes precedence over `aliyun_image_id`). Must match the architecture specified in `arch` parameter. For example, use `acs:ubuntu_24_04_x64` for `amd64`, `acs:ubuntu_24_04_arm64` for `arm64`. See [Aliyun public image documentation](https://help.aliyun.com/zh/ecs/user-guide/public-mirroring-overview/) for available image families. | -                   |
| `aliyun_key_pair_name`               | SSH Key Pair Name                                      | -                   |
| `aliyun_ecs_self_destruct_role_name` | Instance Self-Destruct Role Name                       | -                   |
| `runner_labels`                      | Runner labels (comma-separated)                        | `self-hosted,Linux,aliyun,spot-instance` |
| `runner_version`                     | GitHub Actions Runner version                          | `2.311.0`           |
| `arch`                               | Architecture (`amd64` or `arm64`)                      | `amd64`             |
| `min_cpu`                            | Minimum CPU cores                                      | `8`                 |
| `min_mem`                            | Minimum memory in GB (auto-calculated if not provided) | -                   |
| `max_cpu`                            | Maximum CPU cores                                      | `64`                |
| `max_mem`                            | Maximum memory in GB (auto-calculated if not provided) | -                   |
| `http_proxy`                         | HTTP Proxy URL                                         | -                   |
| `https_proxy`                        | HTTPS Proxy URL                                        | -                   |
| `no_proxy`                           | NO_PROXY environment variable value                    | -                   |
| `vswitch_id_a` to `vswitch_id_z`     | VSwitch IDs for each availability zone                 | -                   |

**Important Note - Proxy Configuration (Mainland China Regions)**: While proxy parameters are technically optional, if you are using Aliyun ECS instances in Mainland China regions (e.g., `cn-hangzhou`, `cn-beijing`), **it is strongly recommended to configure a proxy** due to network restrictions. Without a proxy, instances may be unable to access GitHub to download GitHub Actions Runner binaries and other required resources, which will cause runner initialization to fail. Ensure your proxy server can access `github.com` and `githubusercontent.com`.

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

**Strongly Recommended**: For CI/CD tasks, it is strongly recommended to create a VPC environment isolated from production!

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

**Important**: When using this Action, you must provide a pre-configured PAT (Personal Access Token) with appropriate permissions as `github_token`, because the Action needs to call GitHub API's `actions.createRegistrationTokenForRepo` interface via `github_token` to get runner registration token.

**Note**: Simply configuring workflow's `permissions` is not sufficient. You must use a PAT with appropriate permissions.

PAT permission requirements:

- **Classic PAT**: Requires `repo` scope
- **Fine-grained PAT or GitHub Apps**: Requires `actions:write` permission, and **must be set to access all repositories**, because the runner needs to be able to create registration tokens for all repositories

```yaml
permissions:
  contents: read
  actions: write  # Configured, but actual permissions come from PAT
```

**Important**: Even if `permissions` is configured in the workflow, if the `github_token` (PAT) used does not have the appropriate permissions, it will still fail to get registration token and result in errors.

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
      "Action": ["vpc:DescribeVSwitches", "vpc:DescribeVpcs"],
      "Resource": "*"
    }
  ]
}
```

#### Instance Self-Destruct Role (Optional)

If enabling instance self-destruct feature, you need to create an ECS instance role and grant permissions to delete instances. The self-destruct mechanism allows ECS instances to be automatically deleted after Runner tasks complete, avoiding resource waste.

##### Create RAM Role

1. **Log in to RAM Console**
   - Visit [RAM Console](https://ram.console.aliyun.com/)
   - Navigate to "Identity Management" > "Roles" in the left sidebar

2. **Create Role**

   ```bash
   # Create role using Aliyun CLI
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

   Or create via console:
   - Click "Create Role"
   - Select "Alibaba Cloud Service" as trusted entity type
   - Select "Elastic Compute Service" as trusted service
   - Set role name (e.g., `EcsSelfDestructRole`)
   - Complete creation

##### Grant Instance Deletion Permissions

###### Recommended: Use Minimum Permission Policy

Create a custom policy that only grants instance deletion permissions:

```bash
# Create custom policy
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

# Grant policy to role
aliyun ram AttachPolicyToRole \
  --PolicyType Custom \
  --PolicyName EcsSelfDestructPolicy \
  --RoleName EcsSelfDestructRole
```

**Or grant via console:**

- In role details page, click "Add Permissions"
- Search and select custom policy `EcsSelfDestructPolicy` (or use `AliyunECSFullAccess` for full permissions, not recommended)
- Complete authorization

##### Configure GitHub Variables

Add Variable in GitHub repository settings:

- `ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME`: Set to the created role name (e.g., `EcsSelfDestructRole`)

##### Instance Self-Destruct How It Works

1. **Role Binding**: When creating ECS instance, the role is attached via `--RamRoleName` parameter
2. **Self-Destruct Script**: On instance startup, User Data script creates self-destruct script at `/usr/local/bin/self-destruct.sh`
3. **Permission Acquisition**: Self-destruct script obtains role temporary credentials via instance metadata service:

   ```bash
   curl http://100.100.100.200/latest/meta-data/ram/security-credentials/EcsSelfDestructRole
   ```

4. **Auto Deletion**: After Runner task completes, self-destruct script is executed via post-job hook or systemd service, using role permissions to call `DeleteInstance` API to delete the instance

##### Verify Configuration

- Check instance logs: `/var/log/user-data.log` should show role configuration information
- Check self-destruct logs: `/var/log/self-destruct.log` records deletion process
- Test: Create a test instance, wait for Runner to complete task, then verify instance is automatically deleted

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

1. **Select Optimal Instance**: Use `spot-instance-advisor` tool to query for optimal Spot instances
2. **Create Instance**: Call Aliyun API to create ECS Spot instance, passing User Data script
3. **Configure Runner**: Instance automatically executes User Data script on startup to install and configure GitHub Actions Runner
4. **Wait for Online**: Poll to check if Runner successfully registers and comes online
5. **Auto Cleanup**: Automatically delete instance after Runner task completes (via post-job hook or systemd service)

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
