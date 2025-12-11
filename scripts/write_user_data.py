#!/usr/bin/env python3
"""
Write User Data to file
Read base64-encoded User Data content from environment variable, decode and write to specified file
Avoid exposing sensitive information in GitHub Actions logs, and avoid escaping and parsing issues
"""

import sys
import os
import base64
import binascii


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: write_user_data.py <output_file>", file=sys.stderr)
        sys.exit(1)

    output_file = sys.argv[1]

    # Read base64-encoded User Data from environment variable (prefer env var to avoid showing in logs)
    user_data_b64 = os.environ.get("USER_DATA_B64", "")

    # If environment variable is empty, try reading from stdin (backward compatible)
    if not user_data_b64:
        user_data_b64 = sys.stdin.read().strip()

    if not user_data_b64:
        print("Error: User Data content is empty", file=sys.stderr)
        sys.exit(1)

    # Decode base64
    try:
        user_data = base64.b64decode(user_data_b64).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as e:
        print(f"Error: Failed to decode base64 User Data: {e}", file=sys.stderr)
        sys.exit(1)

    # Write to file
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(user_data)

        # Output file size (for verification)
        file_size = len(user_data.encode("utf-8"))
        print(
            f"User Data file created: {output_file} ({file_size} bytes)",
            file=sys.stderr,
        )
    except OSError as e:
        print(f"Error: Failed to write User Data to {output_file}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
