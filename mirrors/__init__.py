#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

import os
import time
import json
import logging
import socket
import threading
import queue
import glob
from gi.repository import GLib
from .util import Util
from .util import FlexObject


def get_plugin_list():
    return [
        "mesh",
    ]


def get_plugin_properties(name):
    if name == "mesh":
        return dict()
    else:
        assert False


def get_plugin_object(name):
    if name == "mesh":
        return _PluginObject()
    else:
        assert False


class _PluginObject:

    def init2(self, cfg, reflex_environment):
        self.logger = logging.getLogger(self.__module__ + "." + self.__class__.__name__)

        self.cfgObj = cfg

        self.envObj = reflex_environment
        self.envObj.set_plugin_data("mesh", {
            "peer-list": dict(),
        })

        self.netPeerDict = dict()           # dict<hostname, _NetPeer>
        self.diskPeerDict = dict()          # dict<hostname, _DiskPeerData>
        self.netStandbyPeerSet = set()      # set<hostname>
        self._load()

        self.reflexDict = dict()            # dict<reflex-fullname, (reflex-property-dict, reflex-object)>

        self.apiServer = _ApiServer(self)

        self.opmList = []
        for fn in glob.glob(os.path.join(os.path.dirname(__file__), "opm", "*.py")):
            bn = os.path.basename(fn)
            mod = bn[:-3]
            exec("from .opm.%s import OnlinePeerManager" % (mod))
            obj = eval("OnlinePeerManager(self.cfg, self.logger, self.apiServer.port, self.on_net_peer_appear, self.on_net_peer_disappear, self.on_net_peer_wakeup_change)")
            self.opmList.append(obj)

    def dispose(self):
        for obj in self.opmList:
            obj.dispose()
        self.apiServer.close()

    def get_good_reflexes(self, reflex_name, reflex_properties):
        if reflex_properties["role"] in ["server", "p2p"]:
            return [reflex_name]

        if reflex_properties["role"] in ["server-per-client", "p2p-per-peer"]:
            ret = []
            for peername in self.envObj.get_plugin_data("mesh")["peer-list"]:
                ret.append(reflex_name + "." + peername)
            return ret

        if reflex_properties["role"] == "client":
            ret = []
            for peername, peerdata in self.envObj.get_plugin_data("mesh")["peer-list"].items():
                for reflex_fullname, reflex_data in peerdata["reflex-list"].items():
                    if reflex_data["protocol"] == reflex_properties["protocol"]:
                        if reflex_data["role"] == "server":
                            ret.append(reflex_name + "." + peername)
                        elif reflex_data["role"] == "server-per-client" and reflex_fullname == reflex_name + "." + socket.gethostname():
                            ret.append(reflex_name + "." + peername)
            return ret

    def reflex_pre_init(self, reflex_fullname, reflex_properties, obj):
        # record
        reflex_properties = reflex_properties.copy()
        reflex_properties.pop("knowledge")
        reflex_properties.pop("hint-in")
        reflex_properties.pop("hint-out")
        self.reflexDict[reflex_fullname] = (reflex_properties, obj)

        # modify obj
        if reflex_properties["role"] in ["server", "p2p"]:
            obj.send_message_to_peer = lambda peername, data: self._send_message(reflex_fullname, peername, data)
            obj.get_file_from_peer = lambda peername, peer_filename: self._get_file_from_peer(reflex_fullname, peername, peer_filename)
            obj.pull_file_from_peer = lambda peername, peer_filename, local_filename: self._pull_file_from_peer(reflex_fullname, peername, peer_filename, local_filename)
            obj.pull_directory_from_peer = lambda peername, peer_dirname, local_dirname, exclude_pattern=None, include_pattern=None: self._pull_directory_from_peer(reflex_fullname, peername, peer_dirname, local_dirname, exclude_pattern, include_pattern)
        elif reflex_properties["role"] in ["server-per-client", "p2p-per-peer"]:
            peername = reflex_fullname.split(".")[1]
            obj.peer_info = {
                "hostname": peername,
                "ip": self.netPeerDict[peername],
            }
            obj.send_message_to_peer = lambda data: self._send_message(reflex_fullname, peername, data)
            obj.get_file_from_peer = lambda peer_filename: self._get_file_from_peer(reflex_fullname, peername, peer_filename)
            obj.pull_file_from_peer = lambda peer_filename, local_filename: self._pull_file_from_peer(reflex_fullname, peername, peer_filename, local_filename)
            obj.pull_directory_from_peer = lambda peer_dirname, local_dirname, exclude_pattern=None, include_pattern=None: self._pull_directory_from_peer(reflex_fullname, peername, peer_dirname, local_dirname, exclude_pattern, include_pattern)
        else:
            assert False

        # send to peer
        data = {
            "reflex-add": {
                reflex_fullname: reflex_properties,
            }
        }
        for peername in self.netPeerDict:
            self.netPeerDict[peername].messageQueue.put(data)

    def reflex_post_fini(self, reflex_fullname, reflex_properties):
        # record
        del self.reflexDict[reflex_fullname]

        # send to peer
        data = {
            "reflex-remove": [
                reflex_fullname,
            ]
        }
        for peername in self.netPeerDict:
            self.netPeerDict[peername].messageQueue.put(data)

    def on_net_peer_appear(self, peername, ip, port, net_type, can_wakeup):
        if peername in self.netStandbyPeerSet:
            self.netStandbyPeerSet.remove(peername)
        self.netPeerDict[peername] = _NetPeer(ip, port, net_type, can_wakeup)
        self._save()
        self.logger.info("Network peer %s(%s:%d) appeared." % (peername, ip, port))

        self.envObj.get_plugin_data("mesh")["peer-list"][peername] = {
            "reflex-list": dict()
        }
        self.envObj.changed()

    def on_net_peer_disappear(self, peername):
        ip = self.netPeerDict[peername].ip
        port = self.netPeerDict[peername].port
        if self.netPeerDict[peername].can_wakeup:
            self.netStandbyPeerSet.add(peername)
        del self.netPeerDict[peername]
        self._save()
        self.logger.info("Network peer %s(%s:%d) disappeared." % (peername, ip, port))

        del self.envObj.get_plugin_data("mesh")["peer-list"][peername]
        self.envObj.changed()

    def on_net_peer_wakeup_change(self, peername, value):
        self.netPeerDict[peername].can_wakeup = value
        self._save()

    def on_disk_peer_appear(self, peername, dev):
        self.diskPeerDict[peername] = _DiskPeerData(dev)

    def on_disk_peer_disappear(self, peername):
        del self.diskPeerDict[peername]

    def on_peer_reflex_add(self, peername, reflex_fullname, reflex_property_dict):
        self.envObj.get_plugin_data("mesh")["peer-list"][peername]["reflex-list"][reflex_fullname] = reflex_property_dict
        self.logger.info("Network peer %s gets reflex \"%s\"." % (peername, reflex_fullname))
        self.envObj.changed()

    def on_peer_reflex_removed(self, peername, reflex_fullname):
        del self.envObj.get_plugin_data("mesh")["peer-list"][peername]["reflex-list"][reflex_fullname]
        self.logger.info("Network peer %s loses reflex \"%s\"." % (peername, reflex_fullname))
        self.envObj.changed()

    def on_peer_message_received(self, peername, reflex_fullname, data):
        reflex_properties = self.envObj.get_plugin_data("mesh")["peer-list"][peername]["reflex-list"][reflex_fullname]

        fullname = self._match_reflex(peername, reflex_fullname, reflex_properties)
        if fullname is None:
            self.logger.warn("Reject message from non-exist reflex %s on peer %s." % (reflex_fullname, peername))
            return

        if self._reflex_split_fullname(fullname)[1] == "":
            self.reflexDict[fullname][1].on_receive_message_from_peer(peername, data)
        else:
            self.reflexDict[fullname][1].on_receive_message_from_peer(data)

    def _send_message(self, reflex_fullname, peername, data):
        data2 = {
            "app-message": {
                "source": reflex_fullname,
                "data": data,
            }
        }
        self.netPeerDict[peername].messageQueue.put(data2)

    def _get_file_from_peer(self, reflex_fullname, peername, peer_filename):
        return -1

    def _pull_file_from_peer(self, reflex_fullname, peername, peer_filename, local_filename):
        return -1

    def _pull_directory_from_peer(self, reflex_fullname, peername, peer_dirname, local_dirname, exclude_pattern=None, include_pattern=None):
        return -1

    def _match_reflex(self, peername, reflex_fullname, reflex_properties):
        name, insname = _reflex_split_fullname(reflex_fullname)
        assert insname == socket.gethostname() if insname != "" else True

        for fullname2, value in self.reflexDict.items():
            name2, insname2 = _reflex_split_fullname(fullname2)
            prop2 = value[0]
            if self.__match(name, insname, reflex_properties, name2, insname2, prop2, peername):
                return fullname2
        return None

    def _match_peer_reflex(self, peername, reflex_fullname, reflex_properties):
        name, insname = _reflex_split_fullname(reflex_fullname)
        assert insname == peername if insname != "" else True

        for fullname2, prop2 in self.envObj.get_plugin_data("mesh")["peer-list"][peername]["reflex-list"].items():
            name2, insname2 = _reflex_split_fullname(fullname2)
            if self.__match(name, insname, reflex_properties, name2, insname2, prop2, socket.gethostname()):
                return fullname2
        return None

    def __match(name, insname, prop, name2, insname2, prop2, hostname):
        if name2 != name:
            return False
        if insname2 != "" and insname2 != hostname:
            return False
        if prop2["protocol"] != prop["protocol"]:
            return False
        if prop2["role"] == "server" and prop["role"] == "client":
            return True
        if prop2["role"] == "server-per-client" and prop["role"] == "client":
            return True
        if prop2["role"] == "client" and prop["role"] == "server":
            return True
        if prop2["role"] == "client" and prop["role"] == "server-per-client":
            return True
        if prop2["role"] == "p2p" and prop["role"] == "p2p":
            return True
        if prop2["role"] == "p2p" and prop["role"] == "p2p-per-peer":
            return True
        if prop2["role"] == "p2p-per-peer" and prop["role"] == "p2p":
            return True
        if prop2["role"] == "p2p-per-peer" and prop["role"] == "p2p-per-peer":
            return True
        return False

    def _load(self):
        pass

    def _save(self):
        pass


class _NetPeer(threading.Thread):

    def __init__(self, ip, port, net_type, can_wakeup):
        super().__init__()

        assert net_type in ["broadband", "narroband", "traffic-billing"]

        self.ip = ip
        self.port = port
        self.net_type = net_type
        self.can_wakeup = can_wakeup

        self.messageQueue = queue.Queue()
        self.sendThread = None
        self.bStop = False
        self.start()

    def dispose(self):
        self.bStop = True
        self.messageQueue.put(None)
        self.join()

    def run(self):
        while True:
            data = self.messageQueue.get()
            if data is None:
                return

            while True:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.connect((self.ip, self.port))
                    s.send(json.dumps(data))
                    s.close()
                    s = None
                    break
                except socket.error:
                    if s is not None:
                        s.close()
                    for i in range(0, 10):
                        if self.bStop:
                            return
                        time.sleep(10)

            self.messageQueue.task_done()


class _DiskPeerData:

    def __init__(self, dev):
        self.dev = dev


class _ApiServer:

    def __init__(self, pObj):
        self.pObj = pObj
        self.logger = self.pObj.logger
        self.port = Util.getFreeSocketPort("tcp", 10000, 65535)

        self.serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.serverSock.bind(('0.0.0.0', self.port))
        self.serverSock.listen(5)
        self.serverSock.setblocking(0)
        self.serverSourceId = GLib.io_add_watch(self.serverSock, GLib.IO_IN | _flagError, self.on_accept)

        self.sockDict = dict()

    def close(self):
        if True:
            GLib.source_remove(self.serverSourceId)
            self.serverSock.close()
        for sock, obj in self.sockDict.items():
            GLib.source_remove(obj.watch)
            sock.close()

    def on_accept(self, source, cb_condition):
        try:
            assert not (cb_condition & _flagError)
            assert source == self.serverSock

            new_sock, addr = self.serverSock.accept()
            for p in self.pObj.netPeerDict.values():
                if addr[0] == p.ip:
                    obj = FlexObject()
                    obj.buf = bytes()
                    obj.watch = GLib.io_add_watch(new_sock, GLib.IO_IN | _flagError, self.on_recv)
                    self.sockDict[new_sock] = obj
                    return True

            new_sock.close()
            self.logger.error("%s is not a peer, reject." % (addr[0]))
            return True
        except BaseException:
            self.logger.error("Error occured in accept callback.", exc_info=True)
            return True

    def on_recv(self, source, cb_condition):
        try:
            assert source in self.sockDict

            if cb_condition & _flagError:
                source.close()
                del self.sockDict[source]
                return False

            buf2 = source.recv(4096)
            if len(buf2) == 0:
                self._sendMessageToApplication(source.get_peer_address()[0], self.sockDict[source].buf)
                source.close()
                del self.sockDict[source]
                return False

            self.sockDict[source].buf += buf2
            return True
        except BaseException:
            self.logger.error("Error occured in receive callback", exc_info=True)
            return True

    def _sendMessageToApplication(self, src_ip, buf):
        data = json.loads(buf)

        hostname = None
        for hostname2, data in self.pObj.netPeerDict.items():
            if data.ip == src_ip:
                hostname = hostname2
                break
        if hostname is None:
            raise Exception("invalid message received from %s" % (src_ip))

        if "reflex-add" in data:
            for fullname, propDict in data["reflex-add"].items():
                self.pObj.on_peer_reflex_add(hostname, fullname, propDict)
            return

        if "reflex-remove" in data:
            for fullname in data["reflex-remove"]:
                self.pObj.on_peer_reflex_remove(hostname, fullname)
            return

        if "app-message" in data:
            self.pObj.on_peer_message_received(hostname, data["source"], data["data"])
            return

        raise Exception("invalid message received")


def _reflex_make_fullname(name, instance_name):
    if instance_name == "":
        return name
    else:
        return name + "." + instance_name


def _reflex_split_fullname(fullname):
    tlist = fullname.split(".")
    if len(tlist) == 1:
        return (fullname, "")
    else:
        assert len(tlist) == 2
        return (tlist[0], tlist[1])


_flagError = GLib.IO_PRI | GLib.IO_ERR | GLib.IO_HUP | GLib.IO_NVAL
