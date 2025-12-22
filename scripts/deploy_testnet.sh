#!/bin/bash

# P2S Testnet Deployment Script
# This script deploys the P2S protocol to a testnet environment

set -e

echo "P2S Testnet Deployment Script"
echo "=================================="

# Configuration
TESTNET_NAME="p2s-testnet"
CHAIN_ID=1337
GAS_LIMIT=8000000
GAS_PRICE=1000000000
BOOTNODE_PORT=30303
RPC_PORT=8545
WS_PORT=8546

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo "[INFO] $1"
}

print_warning() {
    echo "[WARNING] $1"
}

print_error() {
    echo "[ERROR] $1"
}

print_header() {
    echo "[HEADER] $1"
}

# Check if Go is installed
check_go() {
    print_header "Checking Go installation..."
    if ! command -v go &> /dev/null; then
        print_error "Go is not installed. Please install Go 1.21 or later."
        exit 1
    fi
    
    GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
    print_status "Go version: $GO_VERSION"
}

# Check if Docker is installed
check_docker() {
    print_header "Checking Docker installation..."
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker."
        exit 1
    fi
    
    DOCKER_VERSION=$(docker --version | awk '{print $3}' | sed 's/,//')
    print_status "Docker version: $DOCKER_VERSION"
}

# Clone and setup Ethereum repository
setup_ethereum() {
    print_header "Setting up Ethereum repository..."
    
    if [ ! -d "go-ethereum" ]; then
        print_status "Cloning go-ethereum repository..."
        git clone https://github.com/ethereum/go-ethereum.git
    else
        print_status "go-ethereum repository already exists"
    fi
    
    cd go-ethereum
    
    # Checkout stable version
    print_status "Checking out stable version..."
    git checkout v1.13.0
    
    # Apply P2S modifications
    print_status "Applying P2S modifications..."
    if [ -d "../consensus" ]; then
        cp -r ../consensus/ ./
        print_status "P2S consensus engine copied"
    fi
    
    if [ -d "../core" ]; then
        cp -r ../core/ ./
        print_status "P2S core types copied"
    fi
    
    if [ -d "../crypto" ]; then
        cp -r ../crypto/ ./
        print_status "P2S crypto implementations copied"
    fi
    
    cd ..
}

# Build P2S Ethereum client
build_p2s_client() {
    print_header "Building P2S Ethereum client..."
    
    cd go-ethereum
    
    print_status "Building geth with P2S consensus..."
    make geth
    
    if [ $? -eq 0 ]; then
        print_status "P2S Ethereum client built successfully"
    else
        print_error "Failed to build P2S Ethereum client"
        exit 1
    fi
    
    cd ..
}

# Create testnet configuration
create_testnet_config() {
    print_header "Creating testnet configuration..."
    
    mkdir -p config/testnet
    
    # Create genesis block configuration
    cat > config/testnet/genesis.json << EOF
{
    "config": {
        "chainId": $CHAIN_ID,
        "homesteadBlock": 0,
        "eip150Block": 0,
        "eip155Block": 0,
        "eip158Block": 0,
        "byzantiumBlock": 0,
        "constantinopleBlock": 0,
        "petersburgBlock": 0,
        "istanbulBlock": 0,
        "berlinBlock": 0,
        "londonBlock": 0,
        "arrowGlacierBlock": 0,
        "grayGlacierBlock": 0,
        "shanghaiBlock": 0,
        "cancunBlock": 0,
        "p2sBlock": 0
    },
    "difficulty": "0x400",
    "gasLimit": "0x7A1200",
    "alloc": {
        "0x0000000000000000000000000000000000000000": {
            "balance": "0x1000000000000000000000000000000000000000000000000000000000000000"
        }
    }
}
EOF
    
    # Create validator configuration
    cat > config/testnet/validator_config.json << EOF
{
    "validators": [
        {
            "address": "0x0000000000000000000000000000000000000000",
            "stake": "1000000000000000000000",
            "reputation": 100,
            "isActive": true
        }
    ],
    "minStake": "1000000000000000000",
    "maxValidators": 100,
    "selectionAlgorithm": "weighted_random"
}
EOF
    
    # Create network configuration
    cat > config/testnet/network_config.json << EOF
{
    "networkId": $CHAIN_ID,
    "bootnodes": [],
    "staticNodes": [],
    "trustedNodes": [],
    "maxPeers": 50,
    "maxPendingPeers": 10,
    "dialTimeout": 10,
    "handshakeTimeout": 5,
    "idleTimeout": 30
}
EOF
    
    print_status "Testnet configuration created"
}

# Initialize testnet
init_testnet() {
    print_header "Initializing testnet..."
    
    # Create testnet directory
    mkdir -p testnet
    
    # Initialize genesis block
    print_status "Initializing genesis block..."
    ./go-ethereum/build/bin/geth --datadir testnet init config/testnet/genesis.json
    
    if [ $? -eq 0 ]; then
        print_status "Genesis block initialized successfully"
    else
        print_error "Failed to initialize genesis block"
        exit 1
    fi
}

# Start testnet node
start_testnet() {
    print_header "Starting P2S testnet node..."
    
    # Start the node
    print_status "Starting P2S testnet node..."
    ./go-ethereum/build/bin/geth \
        --datadir testnet \
        --networkid $CHAIN_ID \
        --port $BOOTNODE_PORT \
        --rpc \
        --rpcaddr "0.0.0.0" \
        --rpcport $RPC_PORT \
        --rpcapi "eth,net,web3,personal,admin,miner" \
        --ws \
        --wsaddr "0.0.0.0" \
        --wsport $WS_PORT \
        --wsapi "eth,net,web3,personal,admin,miner" \
        --mine \
        --miner.threads 1 \
        --miner.etherbase "0x0000000000000000000000000000000000000000" \
        --unlock "0x0000000000000000000000000000000000000000" \
        --password <(echo "") \
        --allow-insecure-unlock \
        --nodiscover \
        --maxpeers 0 \
        --verbosity 3 &
    
    NODE_PID=$!
    echo $NODE_PID > testnet/node.pid
    
    print_status "P2S testnet node started with PID: $NODE_PID"
    print_status "RPC endpoint: http://localhost:$RPC_PORT"
    print_status "WebSocket endpoint: ws://localhost:$WS_PORT"
}

# Deploy P2S contracts
deploy_contracts() {
    print_header "Deploying P2S contracts..."
    
    # Wait for node to start
    sleep 10
    
    # Deploy contracts using geth console
    print_status "Deploying P2S contracts..."
    
    # This would typically involve deploying smart contracts
    # For now, we'll just print a placeholder
    print_status "P2S contracts deployment placeholder"
    print_warning "Smart contract deployment not implemented yet"
}

# Run tests
run_tests() {
    print_header "Running P2S tests..."
    
    # Run Go tests
    print_status "Running Go tests..."
    go test ./tests/consensus/ -v
    
    if [ $? -eq 0 ]; then
        print_status "All tests passed"
    else
        print_error "Some tests failed"
        exit 1
    fi
}

# Monitor testnet
monitor_testnet() {
    print_header "Monitoring P2S testnet..."
    
    print_status "Testnet monitoring started"
    print_status "Press Ctrl+C to stop monitoring"
    
    # Monitor node logs
    tail -f testnet/geth.log
}

# Stop testnet
stop_testnet() {
    print_header "Stopping P2S testnet..."
    
    if [ -f testnet/node.pid ]; then
        NODE_PID=$(cat testnet/node.pid)
        kill $NODE_PID
        rm testnet/node.pid
        print_status "P2S testnet node stopped"
    else
        print_warning "No running node found"
    fi
}

# Cleanup
cleanup() {
    print_header "Cleaning up..."
    
    stop_testnet
    
    if [ -d "testnet" ]; then
        rm -rf testnet
        print_status "Testnet directory removed"
    fi
    
    if [ -d "go-ethereum" ]; then
        rm -rf go-ethereum
        print_status "Ethereum repository removed"
    fi
    
    print_status "Cleanup completed"
}

# Main function
main() {
    case "${1:-start}" in
        "start")
            check_go
            check_docker
            setup_ethereum
            build_p2s_client
            create_testnet_config
            init_testnet
            start_testnet
            deploy_contracts
            run_tests
            print_status "P2S testnet deployment completed successfully!"
            print_status "Use './deploy_testnet.sh monitor' to monitor the testnet"
            print_status "Use './deploy_testnet.sh stop' to stop the testnet"
            ;;
        "stop")
            stop_testnet
            ;;
        "monitor")
            monitor_testnet
            ;;
        "cleanup")
            cleanup
            ;;
        "test")
            run_tests
            ;;
        "build")
            check_go
            setup_ethereum
            build_p2s_client
            ;;
        *)
            echo "Usage: $0 {start|stop|monitor|cleanup|test|build}"
            echo ""
            echo "Commands:"
            echo "  start   - Start P2S testnet deployment"
            echo "  stop    - Stop P2S testnet"
            echo "  monitor - Monitor P2S testnet"
            echo "  cleanup - Clean up all files"
            echo "  test    - Run tests only"
            echo "  build   - Build P2S client only"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
