# -*- coding: utf-8 -*-
# Copyright 2015 Metaswitch Networks
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
felix.dispatch
~~~~~~~~~~~~~~

Actor that controls the top-level dispatch chains that dispatch to
per-endpoint chains.
"""
import logging
from calico.felix.actor import Actor, actor_message
from calico.felix.frules import (
    CHAIN_TO_ENDPOINT, CHAIN_FROM_ENDPOINT, chain_names, interface_to_suffix
)

_log = logging.getLogger(__name__)


class DispatchChains(Actor):
    """
    Actor that owns the felix-TO/FROM-ENDPOINT chains, which we use to
    dispatch to endpoint-specific chains.

    LocalEndpoint Actors give us kicks as they come and go so we can
    add/remove them from the chains.
    """

    def __init__(self, config, ip_version, iptables_updater):
        super(DispatchChains, self).__init__(qualifier="v%d" % ip_version)
        self.config = config
        self.ip_version = ip_version
        self.iptables_updater = iptables_updater
        self.ifaces = set()
        self._dirty = False

    @actor_message()
    def apply_snapshot(self, ifaces):
        """
        Replaces all known interfaces with the given snapshot and rewrites the
        chain.

        :param set[str] ifaces: The interface
        """
        _log.info("Applying dispatch chains snapshot.")
        self.ifaces = set(ifaces)  # Take a copy.
        # Always reprogram the chain, even if it's empty.  This makes sure that
        # we resync and it stops the iptables layer from marking our chain as
        # missing.
        self._dirty = True

    @actor_message()
    def on_endpoint_added(self, iface_name):
        """
        Message sent to us by the LocalEndpoint to tell us we should
        add it to the dispatch chain.

        Idempotent: does nothing if the mapping is already in the
        chain.

        :param iface_name: name of the linux interface.
        """
        _log.debug("%s ready: %s", self, iface_name)
        if iface_name in self.ifaces:
            return

        self.ifaces.add(iface_name)
        self._dirty = True

    @actor_message()
    def on_endpoint_removed(self, iface_name):
        """
        Removes the mapping for the given interface name.

        Idempotent: does nothing if there is no mapping.
        """
        _log.debug("%s asked to remove dispatch rule %s", self, iface_name)
        # It should be present but be defensive and reprogram the chain
        # just in case if not.
        try:
            self.ifaces.remove(iface_name)
        except KeyError:
            _log.warning(
                'Attempted to remove unmanaged interface %s', iface_name
            )
        else:
            self._dirty = True

    def _finish_msg_batch(self, batch, results):
        if self._dirty:
            _log.debug("Interface mapping changed, reprogramming chains.")
            self._reprogram_chains()
            self._dirty = False

    def _reprogram_chains(self):
        """
        Recalculates the chains and writes them to iptables.

        Synchronous, doesn't return until the chain is in place.
        """
        _log.info("%s Updating dispatch chain, num entries: %s", self,
                  len(self.ifaces))
        to_upds = []
        from_upds = []
        updates = {CHAIN_TO_ENDPOINT: to_upds,
                   CHAIN_FROM_ENDPOINT: from_upds}
        to_deps = set()
        from_deps = set()
        dependencies = {CHAIN_TO_ENDPOINT: to_deps,
                        CHAIN_FROM_ENDPOINT: from_deps}
        for iface in self.ifaces:
            # Add rule to global chain to direct traffic to the
            # endpoint-specific one.  Note that we use --goto, which means
            # that the endpoint-specific chain will return to our parent
            # rather than to this chain.
            ep_suffix = interface_to_suffix(self.config, iface)
            to_chain_name, from_chain_name = chain_names(ep_suffix)
            from_upds.append("--append %s --in-interface %s --goto %s" %
                             (CHAIN_FROM_ENDPOINT, iface, from_chain_name))
            from_deps.add(from_chain_name)
            to_upds.append("--append %s --out-interface %s --goto %s" %
                           (CHAIN_TO_ENDPOINT, iface, to_chain_name))
            to_deps.add(to_chain_name)

        # Both TO and FROM chains end with a DROP so that interfaces that
        # we don't know about yet can't bypass our rules.
        to_upds.append("--append %s --jump DROP" % CHAIN_TO_ENDPOINT)
        from_upds.append("--append %s --jump DROP" % CHAIN_FROM_ENDPOINT)

        self.iptables_updater.rewrite_chains(updates, dependencies,
                                             async=False)

    def __str__(self):
        return (
            self.__class__.__name__ + "<ipv%s,entries=%s>" %
            (self.ip_version, len(self.ifaces))
        )
