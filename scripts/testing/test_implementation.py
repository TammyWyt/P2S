#!/usr/bin/env python3
"""
Implementation Test Script
Tests the consensus implementation without requiring full Ethereum setup
"""

import subprocess
import sys
import os
import time

def run_command(command, description):
    """Run a command and return the result"""
    print(f"[TEST] {description}")
    print(f"   Command: {command}")
    
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            print(f"   [SUCCESS] Success")
            if result.stdout:
                print(f"   Output: {result.stdout.strip()}")
            return True
        else:
            print(f"   [FAILED] Failed")
            if result.stderr:
                print(f"   Error: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"   [ERROR] Exception: {e}")
        return False

def test_go_installation():
    """Test if Go is installed and working"""
    print("\n[TEST] Testing Go Installation")
    print("=" * 40)
    
    # Check Go version
    if not run_command("go version", "Checking Go version"):
        return False
    
    # Check Go environment
    if not run_command("go env GOPATH", "Checking Go environment"):
        return False
    
    return True

def test_implementation():
    """Test P2S implementation"""
    print("\n[TEST] Testing P2S Implementation")
    print("=" * 40)
    
    # Check if we're in the right directory
    if not os.path.exists("consensus/p2s"):
        print("[FAILED] P2S consensus directory not found")
        return False
    
    # Test Go modules
    if not run_command("go mod init p2s-test", "Initializing Go module"):
        return False
    
    # Test compilation
    if not run_command("go build ./consensus/p2s/...", "Building P2S consensus"):
        return False
    
    # Test core types
    if not run_command("go build ./core/types/...", "Building core types"):
        return False
    
    return True

def test_tests():
    """Test P2S test suite"""
    print("\n[TEST] Testing P2S Test Suite")
    print("=" * 40)
    
    # Run tests
    if not run_command("go test ./tests/consensus/ -v", "Running P2S tests"):
        return False
    
    return True

def test_deployment_script():
    """Test deployment script"""
    print("\n[TEST] Testing Deployment Script")
    print("=" * 40)
    
    # Check if deployment script exists
    if not os.path.exists("scripts/deploy_testnet.sh"):
        print("[FAILED] Deployment script not found")
        return False
    
    # Check if script is executable
    if not os.access("scripts/deploy_testnet.sh", os.X_OK):
        print("[FAILED] Deployment script is not executable")
        return False
    
    # Test script help
    if not run_command("./scripts/deploy_testnet.sh help", "Testing deployment script help"):
        return False
    
    return True

def test_directory_structure():
    """Test directory structure"""
    print("\n[TEST] Testing Directory Structure")
    print("=" * 40)
    
    required_dirs = [
        "consensus/p2s",
        "core/types",
        "crypto/commitment",
        "crypto/signatures",
        "network/p2p",
        "network/rpc",
        "miner",
        "tests/consensus",
        "tests/integration",
        "tests/e2e",
        "scripts/testing",
        "scripts/monitoring",
        "config/testnet",
        "config/mainnet",
        "docs"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"   [SUCCESS] {dir_path}")
        else:
            print(f"   [FAILED] {dir_path}")
            all_exist = False
    
    return all_exist

def test_documentation():
    """Test documentation"""
    print("\n[TEST] Testing Documentation")
    print("=" * 40)
    
    required_docs = [
        "README.md",
        "docs/P2S_PROTOCOL_SPEC.md",
        "docs/CONSENSUS_DESIGN.md"
    ]
    
    all_exist = True
    for doc_path in required_docs:
        if os.path.exists(doc_path):
            print(f"   [SUCCESS] {doc_path}")
        else:
            print(f"   [FAILED] {doc_path}")
            all_exist = False
    
    return all_exist

def main():
    """Main test function"""
    print("[START] Implementation Test Suite")
    print("=" * 50)
    
    tests = [
        ("Go Installation", test_go_installation),
        ("Directory Structure", test_directory_structure),
        ("Documentation", test_documentation),
        ("Implementation", test_implementation),
        ("Tests", test_tests),
        ("Deployment Script", test_deployment_script),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        if test_func():
            passed += 1
            print(f"[SUCCESS] {test_name} PASSED")
        else:
            print(f"[FAILED] {test_name} FAILED")
    
    print(f"\n{'='*50}")
    print(f"[STATS] Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("[COMPLETE] All tests passed! P2S implementation is ready.")
        return 0
    else:
        print("[WARNING] Some tests failed. Please check the implementation.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
