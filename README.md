# Hive Tests

This repository contains automated testing workflows for Ethereum execution clients using [Hive](https://github.com/ethereum/hive), a system for running integration tests against Ethereum clients.

## Overview

Hive Tests runs comprehensive compatibility and conformance tests across multiple Ethereum execution clients to ensure they properly implement the Ethereum protocol. The tests are executed automatically on a daily schedule and can also be triggered manually.

## Supported Clients

The following Ethereum execution clients are tested:

- **[go-ethereum](https://github.com/ethereum/go-ethereum)** (Geth) - The Go implementation of Ethereum
- **[Besu](https://github.com/hyperledger/besu)** - Enterprise-grade Java Ethereum client
- **[Reth](https://github.com/paradigmxyz/reth)** - Rust-based Ethereum execution client
- **[Nethermind](https://github.com/NethermindEth/nethermind)** - .NET Ethereum client
- **[Erigon](https://github.com/ledgerwatch/erigon)** - High-performance Ethereum client
- **[EthereumJS](https://github.com/ethereumjs/ethereumjs-monorepo)** - JavaScript implementation of Ethereum
- **[Nimbus-EL](https://github.com/status-im/nimbus-eth1)** - Nim-based Ethereum execution layer client

## Test Simulators

The repository runs various test simulators including:

- **[ethereum/eest/consume-engine](https://github.com/ethereum/hive/tree/master/simulators/ethereum/eest/consume-engine)**
- **[ethereum/eest/consume-rlp](https://github.com/ethereum/hive/tree/master/simulators/ethereum/eest/consume-rlp)**
- **[ethereum/rpc-compat](https://github.com/ethereum/hive/tree/master/simulators/ethereum/rpc-compat)**
- **[ethereum/consensus](https://github.com/ethereum/hive/tree/master/simulators/ethereum/consensus)**
- **[ethereum/engine](https://github.com/ethereum/hive/tree/master/simulators/ethereum/engine)**
- **[ethereum/sync](https://github.com/ethereum/hive/tree/master/simulators/ethereum/sync)**
- **[ethereum/graphql](https://github.com/ethereum/hive/tree/master/simulators/ethereum/graphql)**
- **[devp2p](https://github.com/ethereum/hive/tree/master/simulators/devp2p)**

## Automation

### Scheduled Runs

Tests run automatically every day via GitHub Actions.

### Manual Execution

You can manually trigger test runs through the GitHub Actions interface with customizable parameters:

- **Client Selection**: Choose which clients to test
- **Simulator Selection**: Choose which test simulators to run
- **Version Control**: Specify custom versions/branches for Hive and each client

## Test Results

Test results are automatically uploaded to:

- **S3 Storage**: Results are stored in the `hive-results` bucket
- **Public Dashboard**: Available at https://hive.ethpandaops.io/
- **GitHub Artifacts**: Downloadable from the workflow runs

## Configuration

The workflow supports testing different versions of clients by specifying repository and tag combinations (e.g., `ethereum/go-ethereum@master`). Default versions are configured for the latest stable branches of each client.

## Infrastructure

Tests run on a combination of:

- GitHub-hosted runners for lighter test suites
- Self-hosted runners for resource-intensive tests (consensus, engine, EEST simulators)

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

## Contributing

This repository is part of the Ethereum testing infrastructure maintained by EthPandaOps. For issues or contributions related to the Hive testing framework itself, please visit the [main Hive repository](https://github.com/ethereum/hive).
