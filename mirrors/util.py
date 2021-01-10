#!/usr/bin/python2
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

import re
import socket
import netifaces
import subprocess


class Util:

    @staticmethod
    def getGatewayIpAddress():
        ret = subprocess.check_output(["/bin/route", "-n4"]).decode("utf-8")
        # syntax: DestIp GatewayIp DestMask ... OutIntf
        m = re.search("^(0\\.0\\.0\\.0)\\s+([0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+)\\s+(0\\.0\\.0\\.0)\\s+.*\\s+(\\S+)$", ret, re.M)
        if m is None:
            return None
        return m.group(2)

    @staticmethod
    def getMyIpAddresses():
        ret = []
        for ifname in netifaces.interfaces():
            if ifname.startswith("lo"):
                continue
            v = netifaces.ifaddresses(ifname)
            if netifaces.AF_INET not in v:
                continue
            ret.append(v[netifaces.AF_INET][0]["addr"])
        return ret

    @staticmethod
    def getFreeSocketPort(portType, portStart, portEnd):
        if portType == "tcp":
            sType = socket.SOCK_STREAM
        elif portType == "udp":
            assert False
        else:
            assert False

        for port in range(portStart, portEnd + 1):
            s = socket.socket(socket.AF_INET, sType)
            try:
                s.bind((('', port)))
                return port
            except socket.error:
                continue
            finally:
                s.close()
        raise Exception("No valid %s port in [%d,%d]." % (portType, portStart, portEnd))


class FlexObject:
    pass
