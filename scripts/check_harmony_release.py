#!/usr/bin/env python3
"""Verify a Huawei-signed repository demo HAP without installing it."""

from run_harmony_demo import find_hdc, validate_hap


def main():
    validate_hap(find_hdc(), physical=True)
    print("HarmonyOS signed HAP: PASS")


if __name__ == "__main__":
    main()
