# Rebootmgr reference guide

## Overview

On a very high level, the functionality can be summarized with the following bullet points:
- `rebootmgr` is a command-line tool, that can be used as a safer replacement for the `reboot` command
- It will only reboot when safe and/or necessary
- You can run it as a systemd timer, or manually
- It relies on Consul service discovery, for a cluster overview
- It can execute tasks before and after rebooting

## Configuration options

You can configure rebootmgr in your cluster using the consul kv store.

### Global stop flag (`service/rebootmgr/stop`)

If this exists in the consul key/value store, rebootmgr won't do anything unless you specify the option `--ignore-global-stop-flag`.

Content of the key does not matter. You can use the content to explain the reason for stopping rebootmgr.

Example for enabling the stop flag:

```
$ consul kv put service/rebootmgr/stop "Stop rebootmgr for some reason"
```

### Ignore failed checks on certain hosts (`service/rebootmgr/ignore_failed_checks`)

If there are failed checks on certain hosts, that you want to be ignored by reboot manager, you can configure a list of hostnames, whose failed checks should be ignored.

Example for ignoring a host:

```
$ consul kv put service/rebootmgr/ignore_failed_checks '["some_hostname"]'
```

### Host-specific configuration (`service/rebootmgr/nodes/{hostname}/config`)

Reboot Manager will be enabled on all hosts by default.

You can disable reboot manager on certain hosts using this key.

Example for disabling reboot manager on `some_hostname`:

```
$ consul kv put service/rebootmgr/nodes/some_hostname/config '{"enabled": False}'
```

## Consul service monitoring

For an overview of how to register services and checks in consul, please refer to [the consul documentation](https://www.consul.io/docs/agent/services.html).

### Relevant services

- If service X is registered to the agent that is being rebooted, health of all instances of service X in the whole cluster (also on other nodes) are taken into consideration.
- Only services with the tag `rebootmgr` will be taken into consideration.
- Rebootmgr will consider services with consul maintenance mode enabled as broken, unless the service is tagged with `ignore_maintenance`
- Rebootmgr assumes that `check_interval + check_timeout < 2 minutes`

Example service definition:

```
{
  "ID": "nova-compute",
  "Name": "nova-compute",
  "Tags": [
  "openstack",
  "rebootmgr"   # leaving the service untagged, it would be ignored by rebootmgr, but still could be queried by a MAT
  ],
  "Check": {
    "Script": "check_nova_compute.sh",
    "Interval": "30s"
  }
}
```

## Task system

Before and after rebooting, rebootmgr can run tasks.

Tasks are simple executable files (usually shell or python scripts).

Rebootmgr is looking for them in `/etc/rebootmgr/pre_boot_tasks/` (for tasks that should be executed before rebooting) and `/etc/rebootmgr/post_boot_tasks/` (for tasks that should run after rebooting).

Tasks will run in alphabetical order by filename.

If a task runtime exceeds two hours, reboot manager will fail and disable itself on that node.

If a task exits with any other code than `0`, reboot manager will fail and not reboot.

## Reboot triggers

Reboot manager will reboot when one of the following is true:

- The option --ignore-triggers has been specified
- The consul key `service/rebootmgr/nodes/{hostname}/reboot_required` is set
- The file `/var/run/reboot-required` exists

## Holidays

If the option --check-holidays is specified, reboot manager will refuse to reboot on german holidays.
