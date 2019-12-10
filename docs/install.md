# Getting started with rebootmgr

At SysEleven, we are using debian packages to install rebootmgr.

As soon as we publish the first release on GitHub, we will add a public Launchpad Repository with a getting-started guide here.

On all nodes to be managed with rebootmgr, run `rebootmgr --ensure-config`,
to ensure that default configuration for the node is present in the
consul key/value store (if not present yet).