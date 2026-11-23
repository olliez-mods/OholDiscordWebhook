import os
import json
import time
import errno
import sys
import socket
import tempfile

# The probe lock needs an OS-level file lock: flock on Linux/macOS, msvcrt on Windows
if(sys.platform == "win32"):
    import msvcrt

    def _try_lock(lock_file):
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(lock_file):
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

    # msvcrt reports a held lock as EACCES or EDEADLOCK depending on the Python build
    _LOCK_BUSY = (errno.EACCES, errno.EAGAIN, errno.EDEADLOCK)
else:
    import fcntl

    def _try_lock(lock_file):
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(lock_file):
        fcntl.flock(lock_file, fcntl.LOCK_UN)

    _LOCK_BUSY = (errno.EACCES, errno.EAGAIN)

# Several copies of this script run side by side on one machine, one per Discord
# server, all on the same minute and all probing nearly the same host list. Without
# coordination that's one connection per host per instance. This module lets the first
# instance of each cycle do the probing and the rest read what it found.

CACHE_VERSION = 1

DEFAULT_CACHE_PATH = "~/.cache/ohol-live-status/status.json"
DEFAULT_TTL = 45          # Under the 60s run interval, so every cycle refreshes once
DEFAULT_LOCK_TIMEOUT = 10 # Worst case hold is ~1s per host, so this has headroom

SERVER_PORT = 8005
SOCKET_TIMEOUT = 1


def probe_server(server:str) -> dict:
    """Ask one server for its player count. Never raises - a failure is a result."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(SOCKET_TIMEOUT)
            s.connect((server, SERVER_PORT))
            s.settimeout(SOCKET_TIMEOUT)
            data = s.recv(1024).split()[1].split(b'/')
            return {"online": True, "players": int(data[0]), "capacity": int(data[1]), "ts": int(time.time())}
    # A malformed reply is as unusable as no reply, and one instance now probes on
    # behalf of the others, so it must not die partway through the host list
    except (socket.error, IndexError, ValueError) as e:
        print(e)
        return {"online": False, "ts": int(time.time())}


def _cache_path(settings:dict) -> str:
    return os.path.expanduser(settings.get("cache_path", DEFAULT_CACHE_PATH))


def _read_cache(path:str) -> dict:
    try:
        with open(path, "r") as cf:
            cache = json.load(cf)
    except (OSError, ValueError):
        return {}
    if(cache.get("version") != CACHE_VERSION): return {} # Written by another version, ignore it
    servers = cache.get("servers")
    return servers if isinstance(servers, dict) else {}


def _write_cache(path:str, servers:dict):
    """Replace the cache in one atomic step, so a reader never sees a half-written file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok = True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir = directory) # Same filesystem, so os.replace is atomic
    try:
        with os.fdopen(tmp_fd, "w") as tf:
            json.dump({"version": CACHE_VERSION, "servers": servers}, tf)
        os.replace(tmp_path, path)
    except BaseException:
        try: os.unlink(tmp_path)
        except OSError: pass
        raise


def _stale_servers(cached:dict, servers, ttl:int, now:int) -> list:
    stale = []
    for server in servers:
        entry = cached.get(server)
        if(not entry or now - entry.get("ts", 0) >= ttl): stale.append(server)
    return stale


def _acquire_lock(path:str, timeout:int):
    """Take the shared probe lock, or give up after `timeout` and return None."""
    os.makedirs(os.path.dirname(path), exist_ok = True)
    lock_file = open(path, "w")
    deadline = time.time() + timeout
    while True:
        try:
            _try_lock(lock_file)
            return lock_file
        except OSError as e:
            if(e.errno not in _LOCK_BUSY):
                lock_file.close()
                raise
            if(time.time() >= deadline):
                lock_file.close()
                return None
            time.sleep(0.1)


def _release_lock(lock_file):
    try:
        _unlock(lock_file)
    finally:
        lock_file.close()


def get_statuses(servers, settings:dict) -> dict:
    """Return {server: status} for every requested server, probing only what's stale.

    Falls back to probing directly if the cache is disabled or unusable, so a broken
    cache can slow this down but can never stop it returning results.
    """
    # .get throughout: the other instances may have config.ini files predating these keys
    if(not settings.get("cache", True)):
        return {server: probe_server(server) for server in servers}

    ttl = int(settings.get("cache_ttl", DEFAULT_TTL))
    path = _cache_path(settings)

    cached = _read_cache(path)
    stale = _stale_servers(cached, servers, ttl, int(time.time()))
    if(not stale):
        print(f"[cache] hit, {len(servers)} servers, no probing")
        return {server: cached[server] for server in servers}

    lock_file = _acquire_lock(f"{path}.lock", int(settings.get("cache_lock_timeout", DEFAULT_LOCK_TIMEOUT)))
    if(lock_file is None):
        # Someone is probing but is taking too long. Serve what we have rather than
        # pile onto the servers, and only probe what we have nothing at all for
        print("[cache] lock timeout, using stale entries")
        results = {}
        for server in servers:
            results[server] = cached[server] if server in cached else probe_server(server)
        return results

    try:
        # Re-read under the lock: while we waited, another instance almost certainly
        # refreshed these already. This is what stops all six probing at once
        cached = _read_cache(path)
        stale = _stale_servers(cached, servers, ttl, int(time.time()))
        if(stale):
            print(f"[cache] probing {len(stale)} of {len(servers)} servers")
            for server in stale:
                cached[server] = probe_server(server)
            _write_cache(path, cached)
        else:
            print(f"[cache] hit after lock, {len(servers)} servers, no probing")
    finally:
        _release_lock(lock_file)

    return {server: cached[server] for server in servers}


def oldest_timestamp(statuses:dict, servers) -> int:
    """When the shown data was actually gathered, for the embed's update time."""
    stamps = [statuses[server]["ts"] for server in servers if server in statuses]
    return min(stamps) if stamps else int(time.time())
