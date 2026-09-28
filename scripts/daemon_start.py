#!/usr/bin/env python3
"""Double-fork daemon launcher: survives sandbox shell-session teardown.

Usage: python daemon_start.py <logfile> <cmd> [args...]
Forks twice (grandchild re-parented to PID 1, like the surviving npm process),
detaches stdio to the logfile, then execs the command.
"""
import os
import sys


def daemonize(logfile: str) -> None:
    if os.fork() > 0:
        os._exit(0)  # parent exits
    os.setsid()
    if os.fork() > 0:
        os._exit(0)  # intermediate exits -> grandchild re-parented to PID 1
    fd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)


def main() -> None:
    logfile, cmd = sys.argv[1], sys.argv[2:]
    daemonize(logfile)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()
