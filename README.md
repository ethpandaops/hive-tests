# Hive Tests

This repository contains automated testing workflows for Ethereum execution clients using [Hive](https://github.com/ethereum/hive), a system for running integration tests against Ethereum clients.

## Overview

Hive Tests runs comprehensive compatibility and conformance tests across multiple Ethereum execution clients to ensure they properly implement the Ethereum protocol. The tests are executed automatically on a daily schedule and can also be triggered manually.

## Supported Clients

The following Ethereum execution clients are tested:

- **go-ethereum** (Geth) - The Go implementation of Ethereum
- **Besu** - Enterprise-grade Java Ethereum client
- **Reth** - Rust-based Ethereum execution client
- **Nethermind** - .NET Ethereum client
- **Erigon** - High-performance Ethereum client
- **EthereumJS** - JavaScript implementation of Ethereum
- **Nimbus-EL** - Nim-based Ethereum execution layer client

## Test Simulators

The repository runs various test simulators including:

- **ethereum/eest/consume-engine** - Engine API tests using execution spec tests
- **ethereum/eest/consume-rlp** - RLP encoding/decoding tests
- **ethereum/rpc-compat** - JSON-RPC API compatibility tests
- **ethereum/consensus** - Consensus layer integration tests
- **ethereum/engine** - Engine API tests
- **ethereum/sync** - Synchronization tests
- **ethereum/graphql** - GraphQL API tests
- **devp2p** - Peer-to-peer networking tests

## Automation

### Scheduled Runs
Tests run automatically every day at 02:15 UTC via GitHub Actions.

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
