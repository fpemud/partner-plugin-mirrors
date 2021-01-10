#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

import msghole
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject
from ..util import Util


class OnlinePeerManager(msghole.EndPoint):

    def __init__(self, cfg, logger, myPort, appearFunc, disappearFunc, setWakeupFunc):
        super().__init__()

        self.cfg = cfg
        self.logger = logger
        self.myPort = myPort
        self.appearFunc = appearFunc
        self.disappearFunc = disappearFunc

        self.advhostApiPort = 2222
        self.advhostRetryTimeout = 3600         # in seconds

        self.sc = Gio.SocketClient.new()
        self.sc.set_family(Gio.SocketFamily.IPV4)
        self.sc.set_protocol(Gio.SocketProtocol.TCP)

        self.connectTimer = GObject.timeout_add_seconds(0, self.on_start)
        self.conn = None
        self.clientDict = None

    def dispose(self):
        self.clientDict = None
        if self.connectTimer is not None:
            GLib.source_remove(self.connectTimer)
        if self.iostream is not None:
            self.close(immediate=True)

    def on_start(self):
        self.connectTimer = None
        try:
            if "plugin-mesh" in self.cfg and "gateway-ip" in self.cfg["plugin-mesh"]:
                gip = self.cfg["plugin-mesh"]["gateway-ip"]
            else:
                gip = Util.getGatewayIpAddress()
            self.sc.connect_to_host_async(gip, self.advhostApiPort, None, self.on_connected)
        except BaseException:
            self.logger.error("Failed to establish WRTD-ADVHOST connection", exc_info=True)
            self._restart()
        finally:
            return False

    def on_connected(self, source_object, res):
        try:
            self.conn = source_object.connect_to_host_finish(res)
            self.set_iostream_and_start(self.conn)
            self.logger.info("WRTD-ADVHOST connection established.")
        except BaseException:
            self.logger.error("Failed to establish WRTD-ADVHOST connection", exc_info=True)
            self._restart()
            return

        try:
            self.send_notification("host-property-change", {
                "service-partner": self.myPort,
            })
            self.exec_command("get-host-list",
                              return_callback=self.command_get_host_list_return,
                              error_callback=self.command_get_host_list_error)
        except BaseException:
            self.logger.error("Failed to establish WRTD-ADVHOST connection", exc_info=True)
            self.close()
            self._restart()
            return

    def on_error(self, excp):
        self.logger.error("WRTD-ADVHOST connection disconnected with error.", exc_info=True)
        self._restart()

    def on_close(self):
        pass

    def command_get_host_list_return(self, data):
        for ip, data2 in data.items():
            if ip in Util.getMyIpAddresses():
                continue
            if "hostname" in data2 and "service-partner" in data2:
                port, net_type, can_wakeup = self.__data2info(data2)
                self.appearFunc(data2["hostname"], ip, port, net_type, can_wakeup)
        self.clientDict = data

    def command_get_host_list_error(self, reason):
        self.logger.error("Command \"get-host-list\" error.", exc_info=True)
        self.close()
        self._restart()

    def on_notification_host_add(self, data):
        if self.clientDict is None:
            return

        for ip, data2 in data.items():
            if ip in Util.getMyIpAddresses():
                if "hostname" in data2 and "service-partner" in data2:
                    port, net_type, can_wakeup = self.__data2info(data2)
                    self.appearFunc(data2["hostname"], ip, port, net_type, can_wakeup)
        self.clientDict.update(data)

    def on_notification_host_change(self, data):
        if self.clientDict is None:
            return

        for ip, data2 in data.items():
            if ip in self.clientDict:
                hostname1 = self.clientDict[ip].get("hostname", None)
                hostname2 = data2.get("hostname", None)
                port1 = self.clientDict[ip].get("service-partner", None)
                port2 = data2.get("service-partner", None)
                ok1 = hostname1 is not None and port1 is not None
                ok2 = hostname2 is not None and port2 is not None
                if not ok1 and not ok2:
                    pass
                elif ok1 and not ok2:
                    self.disappearFunc(hostname1)
                elif not ok1 and ok2:
                    port, net_type, can_wakeup = self.__data2info(data2)
                    self.appearFunc(hostname2, ip, port, net_type, can_wakeup)
                else:
                    if hostname1 != hostname2 or port1 != port2:
                        self.disappearFunc(hostname1)
                        port, net_type, can_wakeup = self.__data2info(data2)
                        self.appearFunc_channel_net(hostname2, ip, port, net_type, can_wakeup)
                    else:
                        if ("can-wakeup" in self.clientDict[ip]) != ("can-wakeup" in data2[ip]):
                            can_wakeup = "can-wakeup" in data2
                            self.setWakeupFunc(hostname2, can_wakeup)

    def on_notification_host_remove(self, data):
        if self.clientDict is None:
            return

        for ip in data:
            if ip in self.clientDict:
                if "hostname" in self.clientDict[ip] and "service-partner" in self.clientDict[ip]:
                    self.disappearFunc(self.clientDict[ip]["hostname"])
                del self.clientDict[ip]

    def on_notification_network_list_change(self, data):
        pass

    def _restart(self):
        assert self.connectTimer is None
        for ip, data2 in self.clientDict:
            if "hostname" in data2 and "service-partner" in data2:
                self.disappearFunc(data2["hostname"])
        self.clientDict = None
        self.conn = None
        self.connectTimer = GObject.timeout_add_seconds(self.advhostRetryTimeout, self.on_start)

    def __data2info(self, data):
        port = data["service-partner"]
        net_type = "narrowband" if "through-vpn" in data else "broadband"
        can_wakeup = "can-wakeup" in data
        return (port, net_type, can_wakeup)
