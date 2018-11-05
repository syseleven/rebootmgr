# Sys11 Reboot Manager Tool

Rebootmgr reboots a node when it is necessary and safe to reboot. We have a lot of constrains in our cluster which must be fullfilled before a node can be rebooted, e.g.

 - don't reboot if the galera/zookeeper/cassandra cluster is not healthy
 - don't reboot a compute node with running VMs
 - don't reboot more than one gateway or loadbalancer

To ensure this constrains rebootmgr relies on consul service checks and runs some tasks before and after rebooting. In version 1.0 only on node at a time is rebooted.

Here is what rebootmgr does in a complete run:

  - get consul lock
  - check services
  - run pre boot tasks
  - check services again
  - reboot
  - run post boot tasks
  - release lock 

This tool expects to see a Consul instance on `127.0.0.1:8500`.
The coordination will happen in `/service/rebootmgr`. We use a Consul lock and the key service/rebootmgr/reboot_in_progress to allow only one reboot at a time.

For details, see [the Design Doc](https://intra.syseleven.de/confluence/pages/viewpage.action?spaceKey=CLOUD&title=Design+Document%3A+Unattended+Reboots)

## Configuration

`rebootmgr` does not have local configuration files. All configuration happens with command line parameters or environment variables.
Have a look at `rebootmgr --help`.

Rebootmgr must be enabled in consul key `service/rebootmgr/nodes/$(hostname -f)/config`.

```
{
    "enabled": true
}
```

## Trigger

There are 3 ways to trigger a reboot via rebootmgr:
  - The consul key service/rebootmgr/nodes/<node>/reboot_required exists
  - The file /var/run/reboot-required exists
  - use the `rebootmgr --ignore-trigger` option on the command line

It is possible to install the debian package `update-notifier-common` which creates the file /var/run/reboot-required after the installation of update if ubuntu thinks a reboot is necessary. 

## Tasks

`rebootmgr` runs every executable in /etc/rebootmgr/pre_boot_task and /etc/rebootmgr/post_boot_task in alphabetical order. Rebootmgr checks the exit code of every task. If a task fails, rebootmgr logs the error and exits. It is a good idea to add a check after each task, e.g. [evacuate a compute node](https://gitlab.syseleven.de/openstack/underlay/blob/master/ansible/roles/rebootmgr/files/pre_boot_tasks/50_host_evacuate) and [check that there are no VMs running afterwards](https://gitlab.syseleven.de/openstack/underlay/blob/master/ansible/roles/rebootmgr/files/pre_boot_tasks/51_check_running_vms). 

## Service Checks

`rebootmgr` depends on consul service checks. Every Consul check must have the tag rebootmgr. Rebootmgr gets a list of checks which are deployed for this node and checks every check on the list on the whole cluster. Example: If one gateway has a check for the midolman systemd unit rebootmgr will only reboot if the check is healthy on every node on the whole cluster. 
rebootmgr checks the services twice, before and after the pre boot tasks are run. 

### Defining a service and checks

Services and checks have to follow the [Consul Documentation](https://www.consul.io/docs/index.html). To tell `rebootmgr` to care about a service, it *must* be tagged with `rebootmgr` during the service registration to Consul.


Defined checks *must* complete in under 2 minutes. Complete means, `Interval + check-runtime`! Because it is not possible to query the interval in hindsight, we are currently sticked to the hard coded 2 minutes.

Example service definition:
```
{
  "ID": "nova-compute",
  "Name": "nova-compute",
  "Tags": [
  "mitaka",
  "rebootmgr"   ## <=== Leaving the service untagged, it would be ignored by rebootmgr, but still could be queried by a MAT
  ],
  "Check": {
    "Script": "/home/cglaubitz/check-nova-compute.sh",
    "Interval": "30s"
  }
}
```

## Stop-Flag

It is possible to stop further nodes from rebooting by creating a global Stop-Flag `service/rebootmgr/stop`, containig any value.

## Systemd

rebootmgr is deployed with a systemd unit file. A timer is deployed via ansible. The timer runs rebootmgr every 5 minutes.
