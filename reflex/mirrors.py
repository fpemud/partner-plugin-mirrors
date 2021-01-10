#!/usr/bin/python3
# -*- coding: utf-8; tab-width: 4; indent-tabs-mode: t -*-

"""
{
    "knowledge": [
    ],
    "function": "set account for projects in ~/workspace",
    "dependencies": [
        "command /usr/bin/inotifywait",
        "directory ~/workspace"
    ]
}
"""


import os
import asyncio
import configparser
import partner.brain
import partner.reflex


USERNAME = "fpemud"
USEREMAIL = "fpemud@sina.com"


@partner.reflex.stimuls
async def stimulus():
    proc = subprocess.Popen(["/usr/bin/inotifywait", "-m", "-q", "-e", "create,moved_to,delete_self", os.path.expanduser("~/workspace")],
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        while True:
            # read inotifywait output
            line = await proc.stdout.readline()
            line = bytes.decode(line)
            op = line.split(" ")[1]

            # ~/workspace is deletedReflex
            if op == "DELETE_SELF":
                raise partner.reflex.StimulusError("~/workspace is deleted")

            # stimulus triggered
            if op == "CREATE,ISDIR" or op == "MOVED_TO,ISDIR":
                fn = line.split(" ")[2]
                await partner.reflex.trigger_response("~/workspace/%s discovered" % (fn), response(fn))
    except asyncio.CancelledError, Exception:
        proc.terminate()
        proc.wait()
        raise


@partner.reflex.parallel_response
async def response(data):
    fn = data
    gitDir = os.path.join(os.path.expanduser("~/workspace"), fn)
    gitCfgFile = os.path.join(gitDir, ".git", "config")
    for i in range(1, 3600):
        if not os.path.exists(gitDir):
            raise partner.reflex.ResponseError("~/workspace/%s is deleted" % (fn))
        if not _Util.isGitRepoComplete(gitDir):
            await asyncio.sleep(1)
            continue
        if not os.path.exists(gitCfgFile):
            await asyncio.sleep(1)
            continue

        cfg = configparser.SafeConfigParser()
        cfg.read(gitCfgFile)

        # config username and password
        if not cfg.has_secion("user"):
            cfg.add_section("user")
        if not cfg.has_option("user", "name"):
            cfg.set("user", "name", USERNAME)
        if not cfg.has_option("user", "email"):
            cfg.set("user", "EMAIL", USEREMAIL)

        # config 
        if not cfg.has_section("credential"):
            cfg.add_section("credential")
        if not cfg.has_option("credential", "helper"):
            cfg.set("credential", "helper", "libsecret")

    raise partner.reflex.ResponseError("~/workspace/%s is not ready after 1 hour, strange, a bit angry" % (fn))


class _Util:

    @staticmethod
    def isGitRepoClonedFully(dirPath):
        # from https://stackoverflow.com/questions/13586502/how-to-check-if-a-git-clone-has-been-done-already-with-jgit
        # there's no command to test it, sucks

        gitDir = os.path.join(dirPath, ".git")
        if not os.path.exists(os.path.join(gitDir, "objects")):
            return False
        if not os.path.exists(os.path.join(gitDir, "refs")):
            return False
        if not os.path.exists(os.path.join(gitDir, "reftable"):
            headFile = os.path.join(gitDir, "HEAD")
            if not os.path.exists(headFile):
                return False
            with open(headFile, "r") as f:
                firstLine = f.read().split("\n")[0]
                if not firstLine.startswith("ref: refs/"):
                    if len(firstLine) != 40:
                        return False
                    if re.fullmatch("[0-9A-Za-z]", firstLine) is None:
                        return False

        # FIXME: needs to check the repository has at least one reference
        pass

        return True
