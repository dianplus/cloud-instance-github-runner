#!/usr/bin/env python3
"""
Create Aliyun ECS Spot instance
Used to create Self-hosted Runner instance
"""

import os
import sys
import subprocess
import base64
import json
import re
from typing import Optional, List, Tuple


def error_exit(message: str) -> None:
    """Print error message and exit"""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def get_env_var(name: str, default: Optional[str] = None) -> str:
    """Get environment variable"""
    value = os.environ.get(name, default)
    if value is None:
        error_exit(f"{name} is required")
    return value


def read_user_data(
    user_data_file: Optional[str] = None, user_data: Optional[str] = None
) -> Optional[str]:
    """Read User Data"""
    if user_data_file and os.path.isfile(user_data_file):
        with open(user_data_file, "r", encoding="utf-8") as f:
            raw_data = f.read()
        # Normalize line endings (remove CRLF)
        user_data = raw_data.replace("\r\n", "\n").replace("\r", "\n")
        size = len(user_data.encode("utf-8"))
        print(
            f"Using User Data from file: {user_data_file} ({size} bytes, normalized)",
            file=sys.stderr,
        )
        return user_data
    elif user_data:
        # Normalize line endings
        user_data = user_data.replace("\r\n", "\n").replace("\r", "\n")
        size = len(user_data.encode("utf-8"))
        print(
            f"Using User Data from environment variable ({size} bytes, normalized)",
            file=sys.stderr,
        )
        return user_data
    else:
        print("No User Data provided", file=sys.stderr)
        return None


def ensure_shebang(user_data: str) -> str:
    """Ensure User Data has shebang"""
    if not user_data.startswith("#!"):
        print("User Data missing shebang; prepending #!/bin/bash", file=sys.stderr)
        return "#!/bin/bash\n" + user_data
    return user_data


def encode_user_data(user_data: str) -> str:
    """Encode User Data to base64"""
    try:
        encoded = base64.b64encode(user_data.encode("utf-8")).decode("ascii")
        return encoded
    except (UnicodeEncodeError, UnicodeDecodeError) as e:
        error_exit(f"Failed to encode User Data to base64: {e}")


def get_image_from_family(region_id: str, image_family: str) -> Optional[dict]:
    """Get latest image information from image family"""
    cmd = [
        "aliyun",
        "ecs",
        "DescribeImageFromFamily",
        "--RegionId",
        region_id,
        "--ImageFamily",
        image_family,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)

        if result.returncode != 0:
            print(
                f"Warning: Failed to query image from family {image_family} (exit code: {result.returncode})",
                file=sys.stderr,
            )
            if result.stderr:
                print(f"Error output: {result.stderr[:200]}", file=sys.stderr)
            return None

        if result.stdout:
            try:
                data = json.loads(result.stdout)

                # Image information returned by DescribeImageFromFamily is in the Image field
                if "Image" in data and data["Image"]:
                    image = data["Image"]
                    image_id = image.get("ImageId", "")

                    if image_id:
                        print(
                            f"Found latest image from family {image_family}: {image_id}",
                            file=sys.stderr,
                        )
                        return {"ImageId": image_id}
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse JSON response: {e}", file=sys.stderr)
                return None

        return None
    except (subprocess.SubprocessError, OSError) as e:
        print(
            f"Warning: Failed to query image from family {image_family}: {e}",
            file=sys.stderr,
        )
        return None


def get_image_id(region_id: str) -> str:
    """
    Unified function to get image ID

    Supports multiple methods (in priority order):
    1. Get from image family (ALIYUN_IMAGE_FAMILY)
    2. Get image ID directly from environment variable (ALIYUN_IMAGE_ID, backward compatible)

    Note: The image family must match the architecture specified in ARCH environment variable.
    For example, use acs:ubuntu_24_04_x64 for amd64, acs:ubuntu_24_04_arm64 for arm64.

    Returns image ID
    """
    # Method 1: Priority - get from image family
    image_family = os.environ.get("ALIYUN_IMAGE_FAMILY")

    if image_family:
        print(f"Getting latest image from family: {image_family}", file=sys.stderr)
        image_info = get_image_from_family(region_id, image_family)

        if image_info and image_info.get("ImageId"):
            return image_info["ImageId"]
        else:
            print(
                f"Warning: Failed to get image from family {image_family}, falling back to ALIYUN_IMAGE_ID",
                file=sys.stderr,
            )

    # Method 2: Get image ID directly from environment variable (backward compatible)
    image_id = os.environ.get("ALIYUN_IMAGE_ID")

    if not image_id:
        error_exit(
            "Either ALIYUN_IMAGE_FAMILY or ALIYUN_IMAGE_ID must be set. "
            "If using ALIYUN_IMAGE_ID, it must be provided."
        )

    return image_id


def get_vswitch_id(zone_id: str) -> Optional[str]:
    """Get VSwitch ID based on zone ID"""
    match = re.search(r"-([a-z])$", zone_id)
    if not match:
        return None

    zone_suffix = match.group(1).upper()
    vswitch_var = f"ALIYUN_VSWITCH_ID_{zone_suffix}"
    return os.environ.get(vswitch_var)


def parse_candidates_file(
    candidates_file: str,
) -> List[Tuple[str, str, str, str, Optional[int]]]:
    """Parse candidates file
    Format: INSTANCE_TYPE|ZONE_ID|VSWITCH_ID|SPOT_PRICE_LIMIT|CPU_CORES
    Returns: (instance_type, zone_id, vswitch_id, spot_price_limit, cpu_cores)
    """
    candidates = []
    if not os.path.isfile(candidates_file):
        return candidates

    with open(candidates_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) >= 4:
                instance_type = parts[0]
                zone_id = parts[1]
                vswitch_id = parts[2]
                spot_price_limit = parts[3]
                cpu_cores = int(parts[4]) if len(parts) > 4 and parts[4] else None
                candidates.append((instance_type, zone_id, vswitch_id, spot_price_limit, cpu_cores))

    return candidates


def calculate_spot_price_limit(
    price_per_core: Optional[float],
    cpu_cores: Optional[int],
    default_limit: Optional[str] = None,
) -> Optional[str]:
    """Calculate Spot price limit"""
    if price_per_core and cpu_cores:
        total_price = price_per_core * cpu_cores
        spot_price_limit = total_price * 1.2
        return f"{spot_price_limit:.4f}"
    return default_limit


def get_supported_disk_category(
    region_id: str, instance_type: str, zone_id: Optional[str] = None
) -> str:
    """Get system disk category supported by instance type (fallback strategy)"""
    # Disk category priority: cloud_essd -> cloud_ssd -> cloud_efficiency
    disk_categories = ["cloud_essd", "cloud_ssd", "cloud_efficiency"]

    # If zone is not specified, try to query (optional)
    if not zone_id:
        # First try to query disk categories supported by instance type
        try:
            cmd = [
                "aliyun",
                "ecs",
                "DescribeAvailableResource",
                "--RegionId",
                region_id,
                "--InstanceType",
                instance_type,
                "--DestinationResource",
                "SystemDisk",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            data = json.loads(result.stdout)

            # Parse supported disk categories
            if (
                "AvailableZones" in data
                and "AvailableZone" in data["AvailableZones"]
                and len(data["AvailableZones"]["AvailableZone"]) > 0
            ):
                zone = data["AvailableZones"]["AvailableZone"][0]
                if (
                    "AvailableResources" in zone
                    and "AvailableResource" in zone["AvailableResources"]
                    and len(zone["AvailableResources"]["AvailableResource"]) > 0
                ):
                    resource = zone["AvailableResources"]["AvailableResource"][0]
                    if (
                        "SupportedResources" in resource
                        and "SupportedResource" in resource["SupportedResources"]
                    ):
                        supported = resource["SupportedResources"]["SupportedResource"]
                        supported_categories = [
                            r.get("Value", "") for r in supported if r.get("Value", "")
                        ]

                        # Select first supported disk category by priority
                        for category in disk_categories:
                            if category in supported_categories:
                                print(
                                    f"Instance type {instance_type} supports disk category: {category}",
                                    file=sys.stderr,
                                )
                                return category

        except (subprocess.SubprocessError, json.JSONDecodeError, KeyError) as e:
            print(
                f"Warning: Failed to query supported disk categories: {e}",
                file=sys.stderr,
            )

    # If query fails, use fallback strategy: try to create instance, if fails then fallback
    # Return cloud_essd first, if creation fails, caller can retry other types
    return "cloud_essd"


def create_instance(
    region_id: str,
    image_id: str,
    instance_type: str,
    security_group_id: str,
    vswitch_id: str,
    instance_name: str,
    key_pair_name: Optional[str] = None,
    ram_role_name: Optional[str] = None,
    spot_strategy: str = "SpotAsPriceGo",
    spot_price_limit: Optional[str] = None,
    user_data_b64: Optional[str] = None,
    system_disk_category: Optional[str] = None,
) -> Tuple[int, str]:
    """Create ECS instance"""
    # If disk category is not specified, auto-detect
    if not system_disk_category:
        system_disk_category = get_supported_disk_category(region_id, instance_type)

    cmd = [
        "aliyun",
        "ecs",
        "RunInstances",
        "--RegionId",
        region_id,
        "--ImageId",
        image_id,
        "--InstanceType",
        instance_type,
        "--SecurityGroupId",
        security_group_id,
        "--VSwitchId",
        vswitch_id,
        "--InstanceName",
        instance_name,
        "--InstanceChargeType",
        "PostPaid",
        "--SystemDisk.Category",
        system_disk_category,
        "--SecurityEnhancementStrategy",
        "Deactive",
        "--Tag.1.Key",
        "GITHUB_RUNNER_TYPE",
        "--Tag.1.Value",
        "aliyun-ecs-spot",
    ]

    if key_pair_name:
        cmd.extend(["--KeyPairName", key_pair_name])

    if ram_role_name:
        cmd.extend(["--RamRoleName", ram_role_name])

    if spot_strategy == "SpotWithPriceLimit" and spot_price_limit:
        cmd.extend(
            [
                "--SpotStrategy",
                "SpotWithPriceLimit",
                "--SpotPriceLimit",
                spot_price_limit,
            ]
        )
    else:
        cmd.extend(["--SpotStrategy", "SpotAsPriceGo"])

    if user_data_b64:
        cmd.extend(["--UserData", user_data_b64])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.returncode, result.stdout + result.stderr
    except (subprocess.SubprocessError, OSError) as e:
        return 1, str(e)


def extract_instance_id(response: str) -> Optional[str]:
    """Extract instance ID from response"""
    try:
        data = json.loads(response)
        if isinstance(data, dict):
            instance_id_sets = data.get("InstanceIdSets", {})
            if isinstance(instance_id_sets, dict):
                instance_id_set = instance_id_sets.get("InstanceIdSet", [])
                if isinstance(instance_id_set, list) and len(instance_id_set) > 0:
                    return instance_id_set[0]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Use regex as fallback
    match = re.search(r'"InstanceId"\s*:\s*"([^"]+)"', response)
    if match:
        return match.group(1)

    return None


def main():
    """Main function"""
    # Get parameters from environment variables
    access_key_id = get_env_var("ALIYUN_ACCESS_KEY_ID")
    access_key_secret = get_env_var("ALIYUN_ACCESS_KEY_SECRET")
    region_id = get_env_var("ALIYUN_REGION_ID")
    vpc_id = get_env_var("ALIYUN_VPC_ID")
    security_group_id = get_env_var("ALIYUN_SECURITY_GROUP_ID")
    vswitch_id = os.environ.get("ALIYUN_VSWITCH_ID")
    key_pair_name = os.environ.get("ALIYUN_KEY_PAIR_NAME")
    ram_role_name = os.environ.get("ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME")
    instance_type = os.environ.get("INSTANCE_TYPE")
    instance_name = get_env_var("INSTANCE_NAME")
    user_data_file = os.environ.get("USER_DATA_FILE")
    user_data = os.environ.get("USER_DATA")
    arch = os.environ.get("ARCH", "amd64")
    spot_price_limit = os.environ.get("SPOT_PRICE_LIMIT")
    candidates_file = os.environ.get("CANDIDATES_FILE")

    # Use unified function to get image ID (supports image family)
    image_id = get_image_id(region_id)

    # Configure Aliyun CLI environment variables
    os.environ["ALIBABA_CLOUD_ACCESS_KEY_ID"] = access_key_id
    os.environ["ALIBABA_CLOUD_ACCESS_KEY_SECRET"] = access_key_secret

    # Verify Aliyun CLI is installed
    try:
        subprocess.run(["aliyun", "--version"], capture_output=True, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        error_exit(
            "Aliyun CLI is not installed or not in PATH. "
            "Please ensure aliyun-cli-setup-action is used in the workflow"
        )

    # Verify Aliyun CLI configuration
    print("Verifying Aliyun CLI configuration...", file=sys.stderr)
    try:
        subprocess.run(["aliyun", "configure", "get"], capture_output=True, check=False)
    except (subprocess.SubprocessError, FileNotFoundError):
        print(
            "Warning: Aliyun CLI configuration check failed, but continuing...",
            file=sys.stderr,
        )

    # Read User Data
    user_data_content = read_user_data(user_data_file, user_data)
    if user_data_content:
        user_data_content = ensure_shebang(user_data_content)

    print("=== Creating Spot Instance ===", file=sys.stderr)
    print(f"Instance Name: {instance_name}", file=sys.stderr)
    print(f"Instance Type: {instance_type}", file=sys.stderr)
    print(f"Region: {region_id}", file=sys.stderr)
    print(f"Architecture: {arch}", file=sys.stderr)
    print(f"VPC ID: {vpc_id}", file=sys.stderr)
    print(f"VSwitch ID: {vswitch_id}", file=sys.stderr)
    print(f"Security Group ID: {security_group_id}", file=sys.stderr)
    print(f"Image ID: {image_id}", file=sys.stderr)
    if key_pair_name:
        print(f"Key Pair Name: {key_pair_name}", file=sys.stderr)
    if spot_price_limit:
        print(f"Spot Price Limit: {spot_price_limit}", file=sys.stderr)

    # Implement retry mechanism (if candidates file exists)
    if candidates_file and os.path.isfile(candidates_file):
        candidates = parse_candidates_file(candidates_file)
        candidate_count = len(candidates)
        print(f"Found {candidate_count} candidate instances for retry", file=sys.stderr)

        # Try each candidate result
        for attempt, (
            cand_instance_type,
            cand_zone_id,
            cand_vswitch_id,
            cand_spot_price_limit,
            _cand_cpu_cores,  # Keep in tuple but not used
        ) in enumerate(candidates, 1):
            # VSwitch ID and Spot Price Limit already read from candidates file, no need to recalculate
            if not cand_vswitch_id:
                print(
                    f"Warning: VSwitch ID is empty for candidate {attempt}, skipping",
                    file=sys.stderr,
                )
                continue

            print(
                f"Attempt {attempt}/{candidate_count}: Trying instance type {cand_instance_type} in zone {cand_zone_id}",
                file=sys.stderr,
            )

            # Encode User Data
            user_data_b64 = None
            if user_data_content:
                user_data_b64 = encode_user_data(user_data_content)

            # Determine Spot strategy
            spot_strategy = "SpotWithPriceLimit" if cand_spot_price_limit else "SpotAsPriceGo"

            # Create instance (supports disk category fallback)
            disk_categories = ["cloud_essd", "cloud_ssd", "cloud_efficiency"]
            instance_created = False

            for disk_category in disk_categories:
                print(
                    f"Attempting to create instance with disk category: {disk_category}",
                    file=sys.stderr,
                )
                exit_code, response = create_instance(
                    region_id=region_id,
                    image_id=image_id,
                    instance_type=cand_instance_type,
                    security_group_id=security_group_id,
                    vswitch_id=cand_vswitch_id,
                    instance_name=instance_name,
                    key_pair_name=key_pair_name,
                    ram_role_name=ram_role_name,
                    spot_strategy=spot_strategy,
                    spot_price_limit=cand_spot_price_limit,
                    user_data_b64=user_data_b64,
                    system_disk_category=disk_category,
                )

                # Check if successful
                if exit_code == 0 and response:
                    instance_id = extract_instance_id(response)
                    if instance_id and instance_id != "null":
                        print(
                            f"Spot instance created successfully on attempt {attempt} with disk category: {disk_category}",
                            file=sys.stderr,
                        )
                        print(f"Instance Type: {cand_instance_type}", file=sys.stderr)
                        print(f"Zone: {cand_zone_id}", file=sys.stderr)
                        print(f"VSwitch: {cand_vswitch_id}", file=sys.stderr)
                        instance_created = True
                        print(instance_id)
                        sys.exit(0)
                    else:
                        # Try next disk category
                        print(
                            "Failed to extract instance ID, trying next disk category...",
                            file=sys.stderr,
                        )
                else:
                    # Check error message, if disk category not supported, try next
                    if "InvalidSystemDiskCategory" in response or "not support" in response.lower():
                        print(
                            f"Disk category {disk_category} not supported, trying next...",
                            file=sys.stderr,
                        )
                        continue
                    else:
                        # Other errors, don't continue trying
                        break

            # If all disk categories failed, log error and continue to next candidate
            if not instance_created:
                print(
                    f"Attempt {attempt} failed: All disk categories failed",
                    file=sys.stderr,
                )
                if response:
                    print(f"Response: {response[:500]}...", file=sys.stderr)

        # All candidate results failed
        error_exit(f"Failed to create Spot instance after {candidate_count} attempts")
    else:
        # No candidates file, use original logic (single attempt)
        if not instance_type:
            error_exit("INSTANCE_TYPE is required")

        if not vswitch_id:
            error_exit("ALIYUN_VSWITCH_ID is required")

        # Encode User Data
        user_data_b64 = None
        if user_data_content:
            user_data_b64 = encode_user_data(user_data_content)

        # Determine Spot strategy
        spot_strategy = "SpotWithPriceLimit" if spot_price_limit else "SpotAsPriceGo"

        # Build command display (without UserData)
        cmd_display = f"aliyun ecs RunInstances --RegionId {region_id} --ImageId {image_id} --InstanceType {instance_type} ..."
        if user_data_b64:
            cmd_display += " --UserData <base64-encoded-data>"
        print(f"Executing command: {cmd_display}", file=sys.stderr)
        print("About to execute Aliyun CLI command...", file=sys.stderr)

        # Create instance (supports disk category fallback)
        disk_categories = ["cloud_essd", "cloud_ssd", "cloud_efficiency"]
        instance_created = False
        last_error = None

        for disk_category in disk_categories:
            print(
                f"Attempting to create instance with disk category: {disk_category}",
                file=sys.stderr,
            )
            exit_code, response = create_instance(
                region_id=region_id,
                image_id=image_id,
                instance_type=instance_type,
                security_group_id=security_group_id,
                vswitch_id=vswitch_id,
                instance_name=instance_name,
                key_pair_name=key_pair_name,
                ram_role_name=ram_role_name,
                spot_strategy=spot_strategy,
                spot_price_limit=spot_price_limit,
                user_data_b64=user_data_b64,
                system_disk_category=disk_category,
            )

            # Check if successful
            if exit_code == 0 and response:
                instance_id = extract_instance_id(response)
                if instance_id and instance_id != "null":
                    print(
                        f"Instance created successfully with disk category: {disk_category}",
                        file=sys.stderr,
                    )
                    instance_created = True
                    print(instance_id)
                    sys.exit(0)
                else:
                    # Try next disk category
                    print(
                        "Failed to extract instance ID, trying next disk category...",
                        file=sys.stderr,
                    )
                    last_error = response
            else:
                # Check error message, if disk category not supported, try next
                if "InvalidSystemDiskCategory" in response or "not support" in response.lower():
                    print(
                        f"Disk category {disk_category} not supported, trying next...",
                        file=sys.stderr,
                    )
                    last_error = response
                    continue
                else:
                    # Other errors, don't continue trying
                    last_error = response
                    break

        # All disk categories failed
        if not instance_created:
            error_exit(
                f"Failed to create Spot instance with all disk categories. Last error: {last_error}"
            )


if __name__ == "__main__":
    main()
