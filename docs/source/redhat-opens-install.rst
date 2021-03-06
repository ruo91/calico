.. # Copyright (c) Metaswitch Networks 2015. All rights reserved.
   #
   #    Licensed under the Apache License, Version 2.0 (the "License"); you may
   #    not use this file except in compliance with the License. You may obtain
   #    a copy of the License at
   #
   #         http://www.apache.org/licenses/LICENSE-2.0
   #
   #    Unless required by applicable law or agreed to in writing, software
   #    distributed under the License is distributed on an "AS IS" BASIS,
   #    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
   #    implied. See the License for the specific language governing
   #    permissions and limitations under the License.

Red Hat Enterprise Linux 7 Packaged Install Instructions
========================================================

The instructions come in two sections: one for installing control nodes,
and one for installing compute nodes. Before moving on to those
sections, make sure you follow the **Common Steps** section, and if you
want to create a combined controller and compute node, work through all
three sections.

.. warning:: Following the upgrade to use etcd as a data store, Calico
             currently only supports RHEL 7 and above.
             If support on RHEL 6.x or other versions of Linux is important to
             you, then please `let us know
             <http://www.projectcalico.org/contact/>`_.

Prerequisites
-------------

Before starting this you will need the following:

-  One or more machines running RHEL 7, with OpenStack Juno installed.
-  SSH access to these machines.
-  Working DNS between these machines (use ``/etc/hosts`` if you don't
   have DNS on your network).

Common Steps
------------

Some steps need to be taken on all machines being installed with Calico.
These steps are detailed here.

Install OpenStack Juno
~~~~~~~~~~~~~~~~~~~~~~

If you haven't already done so, install Juno with Neutron and ML2 networking.
Instructions for installing OpenStack on RHEL can be found
`here <http://openstack.redhat.com/Main_Page>`__.

Configure YUM repositories
~~~~~~~~~~~~~~~~~~~~~~~~~~

As well as the repositories for OpenStack and EPEL
(https://fedoraproject.org/wiki/EPEL) -- which you will have already
configured as part of the previous step -- you will need to configure the
repository for Calico::

    cat > /etc/yum.repos.d/calico.repo <<EOF
    [calico]
    name=Calico Repository
    baseurl=http://binaries.projectcalico.org/rpm/
    enabled=1
    skip_if_unavailable=0
    gpgcheck=1
    gpgkey=http://binaries.projectcalico.org/rpm/key
    priority=97
    EOF

Note: The priority setting in ``calico.repo`` is needed so that the
Calico repository can install Calico-enhanced versions of some of the
OpenStack Nova and Neutron packages.

.. _control-node:

Control Node Install
--------------------

On a control node, perform the following steps:

1. Delete all configured OpenStack state, in particular any instances,
   routers, subnets and networks (in that order) created by the install
   process referenced above. You can do this using the web dashboard or
   at the command line.

   .. hint:: The Admin and Project sections of the web dashboard both
             have subsections for networks and routers. Some networks
             may need to be deleted from the Admin section.

   .. warning:: The Calico install will fail if incompatible state is
                left around.

2. Run ``yum update``. This will bring in Calico-specific updates to the
   OpenStack packages and to ``dnsmasq``.

3. Edit the ``/etc/neutron/plugins/ml2/ml2_conf.ini`` file:

   -  Find the ``type_drivers`` setting and change it to read
      ``type_drivers = local, flat``.
   -  Find the ``tenant_network_types`` setting and change it to read
      ``tenant_network_types = local``.
   -  Find the ``mechanism_drivers`` setting and change it to read
      ``mechanism_drivers = calico``.

4. Edit the ``/etc/neutron/neutron.conf`` file:

   -  Find the line for the ``dhcp_agents_per_network`` setting,
      uncomment it, and set its value to the number of compute nodes
      that you will have (or any number larger than that). This allows a
      DHCP agent to run on every compute node, which Calico requires
      because the networks on different compute nodes are not bridged
      together.
   -  Find the lines for ``api_workers`` and ``rpc_workers``, uncomment
      them and set them both to 0.

5. Install and configure etcd. For these instructions we assume you're
   configuring a single-node cluster on only one machine. If you plan to
   deploy a multi-node cluster, please consult the `etcd clustering docs`_, and
   skip to step 7.

   - Download, unpack, and install the binary::

        curl -L  https://github.com/coreos/etcd/releases/download/v2.0.9/etcd-v2.0.9-linux-amd64.tar.gz -o etcd-v2.0.9-linux-amd64.tar.gz
        tar xvf etcd-v2.0.9-linux-amd64.tar.gz
        cd etcd-v2.0.9-linux-amd64
        mv etcd* /usr/local/bin/

   - Create an etcd user::

        adduser -s /sbin/nologin -d /var/lib/etcd/ etcd
        chmod 700 /var/lib/etcd/

   - Add the following line to the bottom of ``/etc/fstab``. This will mount a
     ramdisk for etcd at startup::

       tmpfs /var/lib/etcd tmpfs nodev,nosuid,noexec,nodiratime,size=512M 0 0

   - Run ``mount -a`` to mount it now.

   - Get etcd running by providing an init file.

     Place the following in ``/etc/sysconfig/etcd``, replacing ``<hostname>``
     and ``<public_ip>`` with their appropriate values for the machine.

     ::

           ETCD_DATA_DIR=/var/lib/etcd
           ETCD_NAME=<hostname>
           ETCD_ADVERTISE_CLIENT_URLS="http://<public_ip>:2379,http://<public_ip>:4001"
           ETCD_LISTEN_CLIENT_URLS="http://0.0.0.0:2379,http://0.0.0.0:4001"
           ETCD_LISTEN_PEER_URLS="http://0.0.0.0:2380"
           ETCD_INITIAL_ADVERTISE_PEER_URLS="http://<public_ip>:2380"
           ETCD_INITIAL_CLUSTER="<hostname>=http://<public_ip>:2380"
           ETCD_INITIAL_CLUSTER_STATE=new

     Check the ``uuidgen`` tool is installed (the output should change each
     time)::

           # uuidgen
           11f92f19-cb5a-476f-879f-5efc34033b8b

     If it is not installed, run ``yum install util-linux`` to install it.

     Place the following in ``/usr/local/bin/start-etcd``::

           #!/bin/sh
           export ETCD_INITIAL_CLUSTER_TOKEN=`uuidgen`
           exec /usr/local/bin/etcd

     Then run ``chmod +x /usr/local/bin/start-etcd`` to make that file
     executable.

     You then need to add the following file to
     ``/usr/lib/systemd/system/etcd.service``::

           [Unit]
           Description=Etcd
           After=syslog.target network.target

           [Service]
           User=root
           ExecStart=/usr/local/bin/start-etcd
           EnvironmentFile=-/etc/sysconfig/etcd
           KillMode=process
           Restart=always

           [Install]
           WantedBy=multi-user.target

6. Launch etcd and set it to restart after a reboot::

        systemctl start etcd
        systemctl enable etcd

7. Install dependencies for python-etcd::

        yum groupinstall 'Development Tools'
        yum install python-devel libffi-devel openssl-devel

8. Install python-etcd::

        curl -L https://github.com/Metaswitch/python-etcd/archive/master.tar.gz -o python-etcd.tar.gz
        tar xvf python-etcd.tar.gz
        cd python-etcd-master
        python setup.py install

9. Install the ``calico-control`` package:

   ::

       yum install calico-control

10. Restart the neutron server process:
    ``service neutron-server restart``.

.. _etcd clustering docs: https://github.com/coreos/etcd/blob/master/Documentation/clustering.md

Compute Node Install
--------------------

On a compute node, perform the following steps:

1. Make changes to SELinux and QEMU config to allow VM interfaces with
   ``type='ethernet'``  (`this
   libvirt Wiki page <http://wiki.libvirt.org/page/Guest_won%27t_start_-_warning:_could_not_open_/dev/net/tun_%28%27generic_ethernet%27_interface%29>`__
   explains why these changes are required)::

       setenforce permissive

   Edit ``/etc/selinux/config`` and change the ``SELINUX=`` line to the
   following:

   ::

           SELINUX=permissive

   In ``/etc/libvirt/qemu.conf``, add or edit the following four options:

   ::

           clear_emulator_capabilities = 0
           user = "root"
           group = "root"
           cgroup_device_acl = [
                "/dev/null", "/dev/full", "/dev/zero",
                "/dev/random", "/dev/urandom",
                "/dev/ptmx", "/dev/kvm", "/dev/kqemu",
                "/dev/rtc", "/dev/hpet", "/dev/net/tun",
           ]

   .. note:: The ``cgroup_device_acl`` entry is subtly different to the
             default. It now contains ``/dev/net/tun``.

   Then restart libvirt to pick up the changes:

   ::

           service libvirtd restart

2. Open ``/etc/nova/nova.conf`` and remove the line that reads:

   ::

       linuxnet_interface_driver = nova.network.linux_net.LinuxOVSInterfaceDriver

   Remove the line setting ``service_neutron_metadata_proxy`` or
   ``service_metadata_proxy`` to ``True``, if there is one. Additionally, if
   there is a line setting ``metadata_proxy_shared_secret``, comment that line
   out as well.

   Restart nova compute.

   ::

           service openstack-nova-compute restart

   If this node is also a controller, additionally restart nova-api::

           service openstack-nova-api restart

3. If they're running, stop the Open vSwitch services:

   ::

       service neutron-openvswitch-agent stop
       service openvswitch stop

   Then, prevent the services running if you reboot:

   ::

           chkconfig openvswitch off
           chkconfig neutron-openvswitch-agent off

4. Run ``yum update``. This will bring in Calico-specific updates to the
   OpenStack packages and to ``dnsmasq``.

5. Install build dependencies:

   ::

       yum groupinstall 'Development Tools'

6. Install and configure the DHCP agent on the compute host:

   ::

       yum install openstack-neutron

   Open ``/etc/neutron/dhcp_agent.ini``. In the ``[DEFAULT]`` section, add
   the following line (removing any existing ``interface_driver =`` line):

   ::

           interface_driver = neutron.agent.linux.interface.RoutedInterfaceDriver

7.  Restart and enable the DHCP agent

    ::

        service neutron-dhcp-agent restart
        chkconfig neutron-dhcp-agent on

8.  Stop and disable any other routing/bridging agents such as the L3
    routing agent or the Linux bridging agent.  These conflict with Calico.

    ::

        service neutron-l3-agent stop
        chkconfig neutron-l3-agent off
        ... repeat for bridging agent and any others ...

9.  If this node is not a controller, install and start the Nova
    Metadata API. This step is not required on combined compute and
    controller nodes.

    ::

        yum install openstack-nova-api
        service openstack-nova-metadata-api restart
        chkconfig openstack-nova-metadata-api on

10. Install the BIRD BGP client from EPEL:
    ``yum install -y bird bird6``

11. If this node is not a controller, install and configure etcd as an etcd
    proxy. These assume you followed the instructions in the
    :ref:`control-node` section of this document for your contoller: if you
    installed etcd yourself in some other manner, skip to step 12.

    - Download, unpack, and install the binary::

        curl -L  https://github.com/coreos/etcd/releases/download/v2.0.9/etcd-v2.0.9-linux-amd64.tar.gz -o etcd-v2.0.9-linux-amd64.tar.gz
        tar xvf etcd-v2.0.9-linux-amd64.tar.gz
        cd etcd-v2.0.9-linux-amd64
        mv etcd* /usr/local/bin/

    - Create an etcd user::

        adduser -s /sbin/nologin -d /var/lib/etcd/ etcd
        chmod 700 /var/lib/etcd/

    - Get etcd running by providing an init file.

      Place the following in ``/etc/sysconfig/etcd``, replacing
      ``<controller_hostname>`` and ``<controller_ip>`` with the values you
      used in the :ref:`control-node` section.

      ::

           ETCD_PROXY=on
           ETCD_DATA_DIR=/var/lib/etcd
           ETCD_INITIAL_CLUSTER="<controller_hostname>=http://<controller_ip>:2380"

      You then need to add the following file to
      ``/usr/lib/systemd/system/etcd.service``::

           [Unit]
           Description=Etcd
           After=syslog.target network.target

           [Service]
           User=root
           ExecStart=/usr/local/bin/etcd
           EnvironmentFile=-/etc/sysconfig/etcd
           KillMode=process
           Restart=always

           [Install]
           WantedBy=multi-user.target

12. If this node is not a controller, launch etcd and set it to restart after a
    reboot::

        systemctl start etcd
        systemctl enable etcd


13. If this node is not also a controller, install dependencies for
    python-etcd::

        yum groupinstall 'Development Tools'
        yum install python-devel libffi-devel openssl-devel

14. If this node is not also a controller, install python-etcd::

        curl -L https://github.com/Metaswitch/python-etcd/archive/master.tar.gz -o python-etcd.tar.gz
        tar xvf python-etcd.tar.gz
        cd python-etcd-master
        python setup.py install

14. Install the ``calico-compute`` package:

    ::

        yum install calico-compute

15. Configure BIRD. Calico includes useful configuration scripts that
    will create BIRD config files for simple topologies -- either a
    peering between a single pair of compute nodes, or to a route
    reflector (to avoid the need for a full BGP mesh in networks with
    more than two compute nodes). If your topology is more complex, please
    consult the relevant documentation for your chosen BGP stack or ask
    the mailing list if you have questions about how BGP relates to
    Calico.

    For IPv4 connectivity between compute hosts:

    ::

        /usr/bin/calico-gen-bird-conf.sh <compute_node_ipv4> <peer_ipv4> <bgp_as_number>

    And/or for IPv6 connectivity between compute hosts:

    ::

        /usr/bin/calico-gen-bird6-conf.sh <compute_node_ipv4> <compute_node_ipv6> <peer_ipv6> <bgp_as_number>

    ``<compute_node_ipv4>`` and ``<compute_node_ipv6>`` are the IPv4/6
    addresses of the compute host, used as next hops and router ids.

    ``<peer_ipv4>`` and ``<peer_ipv6>`` are the IP address of your
    single other compute node, or the route reflector as described
    earlier.

    ``<bgp_as_number>`` is the BGP `AS
    number <http://en.wikipedia.org/wiki/Autonomous_System_%28Internet%29>`__.
    Unless your deployment needs to peer with other BGP routers, this
    can be chosen arbitrarily.

   Note that you'll also need to configure your route reflector to allow
   connections from the compute node as a route reflector client. This
   configuration is outside the scope of this install document.

   Ensure BIRD (and/or BIRD 6 for IPv6) is running and starts on reboot:

   ::

         service bird restart
         service bird6 restart
         chkconfig bird on
         chkconfig bird6 on

16. Create the ``/etc/calico/felix.cfg`` file by copying
    ``/etc/calico/felix.cfg.example``.  Ordinarily the default values should be
    used, but see :doc:`configuration` for more details.

17. Restart the Felix service:

       - run ``systemctl restart calico-felix``.

Next Steps
----------

Now you've installed Calico, follow :ref:`opens-install-inst-next-steps` for
details on how to configure networks and use your new deployment.
