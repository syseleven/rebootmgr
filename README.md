# Unattended Reboot Manager

## Overview

Rebootmgr is an operations tool, that can help you safely automate reboots of nodes in complex, distributed environments.

We created rebootmgr for our public cloud offering SysEleven Stack, because we wanted to make sure that our services are always up-to-date and secure.

We noticed that rebootmgr does not only save valuable time for our engineers, it can also reboot more reliably, because it is more vigilant than a human, always keeping an eye on the cluster's health.

## Design

Using consul, rebootmgr is able to have an overview of your cluster's services health. It also uses the locking and key-value store features of Consul to make sure, that only one node in the cluster is rebooting at a time.

For a deep dive how exactly rebootmgr works internally and why we created it, see our [design document](docs/design.md).

## Getting started

If you want to try rebootmgr hands-on, have a look at our [installation guide](docs/install.md).

## Reference

For a deep-dive into rebootmgr usage scenarios, have a look at our [reference guide](docs/reference.md)

## Testing

For running the integration tests you need docker compose. For running the linter and safety checks, you need tox.

```
# Run integration tests with different python versions
$ docker-compose run --rm integration_tests_py38
$ docker-compose run --rm integration_tests_py37
$ docker-compose run --rm integration_tests_py36

# Run linter and safety checks
$ tox -e lint
$ tox -e safety

# Clean up docker
docker-compose down --rmi local -v
```

## Contributing

We would love seeing community contributions for rebootmgr, and are eager to collaborate with you.
