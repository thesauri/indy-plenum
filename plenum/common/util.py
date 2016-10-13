import asyncio
import base58
import base64
import importlib.util
import itertools
import json
import logging
import math
import os
import random
import socket
import string
import time
from binascii import unhexlify, hexlify
from collections import Counter
from collections import OrderedDict
from math import floor
from typing import TypeVar, Iterable, Mapping, Set, Sequence, Any, Dict, \
    Tuple, Union, List, NamedTuple

import libnacl.secret
from ledger.util import F
from libnacl import crypto_hash_sha256
from six import iteritems, string_types

T = TypeVar('T')
Seconds = TypeVar("Seconds", int, float)
CONFIG = None


def randomString(size: int = 20,
                 chars: str = string.ascii_letters + string.digits) -> str:
    """
    Generate a random string of the specified size.

    Ensure that the size is less than the length of chars as this function uses random.choice
    which uses random sampling without replacement.

    :param size: size of the random string to generate
    :param chars: the set of characters to use to generate the random string. Uses alphanumerics by default.
    :return: the random string generated
    """
    return ''.join(random.sample(chars, size))


def mostCommonElement(elements: Iterable[T]) -> T:
    """
    Find the most frequent element of a collection.

    :param elements: An iterable of elements
    :return: element of type T which is most frequent in the collection
    """
    return Counter(elements).most_common(1)[0][0]


def updateNamedTuple(tupleToUpdate: NamedTuple, **kwargs):
    tplData = dict(tupleToUpdate._asdict())
    tplData.update(kwargs)
    return tupleToUpdate.__class__(**tplData)


def objSearchReplace(obj: Any, toFrom: Dict[Any, Any], checked: Set[Any] = set()
                     , logMsg: str = None) -> None:
    """
    Search for an attribute in an object and replace it with another.

    :param obj: the object to search for the attribute
    :param toFrom: dictionary of the attribute name before and after search and replace i.e. search for the key and replace with the value
    :param checked: set of attributes of the object for recursion. optional. defaults to `set()`
    :param logMsg: a custom log message
    """
    checked.add(id(obj))
    pairs = [(i, getattr(obj, i)) for i in dir(obj) if not i.startswith("__")]

    if isinstance(obj, Mapping):
        pairs += [x for x in iteritems(obj)]
    elif isinstance(obj, (Sequence, Set)) and not isinstance(obj, string_types):
        pairs += [x for x in enumerate(obj)]

    for nm, o in pairs:
        if id(o) not in checked:
            mutated = False
            for old, new in toFrom.items():
                if id(o) == id(old):
                    logging.debug("{}in object {}, attribute {} changed from {} to {}".
                                  format(logMsg + ": " if logMsg else "",
                                         obj, nm, old, new))
                    if isinstance(obj, dict):
                        obj[nm] = new
                    else:
                        setattr(obj, nm, new)
                    mutated = True
            if not mutated:
                objSearchReplace(o, toFrom, checked, logMsg)
    checked.remove(id(obj))


def error(msg: str) -> Exception:
    """
    Wrapper to get around Python's distinction between statements and expressions
    Can be used in lambdas and expressions such as: a if b else error(c)

    :param msg: error message
    """
    raise Exception(msg)


def getRandomPortNumber() -> int:
    """
    Get a random port between 8090 and 65530

    :return: a random port number
    """
    return random.randint(8090, 65530)


def isHex(val: str) -> bool:
    """
    Return whether the given str represents a hex value or not

    :param val: the string to check
    :return: whether the given str represents a hex value
    """
    if isinstance(val, bytes):
        # only decodes utf-8 string
        try:
            val = val.decode()
        except:
            return False
    return isinstance(val, str) and all(c in string.hexdigits for c in val)


async def runall(corogen):
    """
    Run an array of coroutines

    :param corogen: a generator that generates coroutines
    :return: list or returns of the coroutines
    """
    results = []
    for c in corogen:
        result = await c
        results.append(result)
    return results


def getSymmetricallyEncryptedVal(val, secretKey: Union[str, bytes]=None) -> Tuple[str, str]:
    """
    Encrypt the provided value with symmetric encryption

    :param val: the value to encrypt
    :param secretKey: Optional key, if provided should be either in hex or bytes
    :return: Tuple of the encrypted value and secret key encoded in hex
    """
    if isinstance(val, str):
        val = val.encode("utf-8")
    if secretKey:
        if isHex(secretKey):
            secretKey = bytes(bytearray.fromhex(secretKey))
        elif not isinstance(secretKey, bytes):
            error("Secret key must be either in hex or bytes")
        box = libnacl.secret.SecretBox(secretKey)
    else:
        box = libnacl.secret.SecretBox()
    return box.encrypt(val).hex(), box.sk.hex()


def getMaxFailures(nodeCount: int) -> int:
    r"""
    The maximum number of Byzantine failures permissible by the RBFT system.
    Calculated as :math:`f = (N-1)/3`

    :param nodeCount: number of nodes in the system
    :return: maximum permissible Byzantine failures in the system
    """
    if nodeCount >= 4:
        return floor((nodeCount - 1) / 3)
    else:
        return 0


def getQuorum(nodeCount: int = None, f: int = None) -> int:
    r"""
    Return the minimum number of nodes where the number of correct nodes is
    greater than the number of faulty nodes.
    Calculated as :math:`2*f + 1`

    :param nodeCount: the number of nodes in the system
    :param f: the max. number of failures
    """
    if nodeCount is not None:
        f = getMaxFailures(nodeCount)
    if f is not None:
        return 2 * f + 1


def getNoInstances(nodeCount: int) -> int:
    """
    Return the number of protocol instances which is equal to f + 1. See
    `getMaxFailures`

    :param nodeCount: number of nodes
    :return: number of protocol instances
    """
    return getMaxFailures(nodeCount) + 1


def prime_gen() -> int:
    # credit to David Eppstein, Wolfgang Beneicke, Paul Hofstra
    """
    A generator for prime numbers starting from 2.
    """
    D = {}
    yield 2
    for q in itertools.islice(itertools.count(3), 0, None, 2):
        p = D.pop(q, None)
        if p is None:
            D[q * q] = 2 * q
            yield q
        else:
            x = p + q
            while x in D:
                x += p
            D[x] = p


def evenCompare(a: str, b: str) -> bool:
    """
    A deterministic but more evenly distributed comparator than simple alphabetical.
    Useful when comparing consecutive strings and an even distribution is needed.
    Provides an even chance of returning true as often as false
    """
    ab = a.encode('utf-8')
    bb = b.encode('utf-8')
    ac = crypto_hash_sha256(ab)
    bc = crypto_hash_sha256(bb)
    return ac < bc


def distributedConnectionMap(names: List[str]) -> OrderedDict:
    """
    Create a map where every node is connected every other node.
    Assume each key in the returned dictionary to be connected to each item in
    its value(list).

    :param names: a list of node names
    :return: a dictionary of name -> list(name).
    """
    names.sort()
    combos = list(itertools.combinations(names, 2))
    maxPer = math.ceil(len(list(combos)) / len(names))
    # maxconns = math.ceil(len(names) / 2)
    connmap = OrderedDict((n, []) for n in names)
    for a, b in combos:
        if len(connmap[a]) < maxPer:
            connmap[a].append(b)
        else:
            connmap[b].append(a)
    return connmap


def checkPortAvailable(ha) -> bool:
    """Returns whether the given port is available"""
    available = True
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(ha)
    except:
        logging.warning("Checked port availability for opening "
                        "and address was already in use: {}".format(ha))
        available = False
    finally:
        sock.close()
    return available


class MessageProcessor:
    """
    Helper functions for messages.
    """

    def discard(self, msg, reason, logMethod=logging.error, cliOutput=False):
        """
        Discard a message and log a reason using the specified `logMethod`.

        :param msg: the message to discard
        :param reason: the reason why this message is being discarded
        :param logMethod: the logging function to be used
        """
        reason = "" if not reason else " because {}".format(reason)
        logMethod("{} discarding message {}{}".format(self, msg, reason),
                  extra={"cli": cliOutput})


class adict(dict):
    """Dict with attr access to keys."""
    marker = object()

    def __init__(self, **kwargs):
        super().__init__()
        for key in kwargs:
            self.__setitem__(key, kwargs[key])

    def __setitem__(self, key, value):
        if isinstance(value, dict) and not isinstance(value, adict):
            value = adict(**value)
        super(adict, self).__setitem__(key, value)

    def __getitem__(self, key):
        found = self.get(key, adict.marker)
        if found is adict.marker:
            found = adict()
            super(adict, self).__setitem__(key, found)
        return found

    __setattr__ = __setitem__
    __getattr__ = __getitem__


def getInstalledConfig(installDir, configFile):
    """
    Reads config from the installation directory of Plenum.

    :param installDir: installation directory of Plenum
    :param configFile: name of the confiuration file
    :raises: FileNotFoundError
    :return: the configuration as a python object
    """
    configPath = os.path.join(installDir, configFile)
    if os.path.exists(configPath):
        spec = importlib.util.spec_from_file_location(configFile,
                                                      configPath)
        config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config)
        return config
    else:
        raise FileNotFoundError("No file found at location {}".format(configPath))


def getConfig(homeDir=None):
    """
    Reads a file called config.py in the project directory

    :raises: FileNotFoundError
    :return: the configuration as a python object
    """
    global CONFIG
    if not CONFIG:
        refConfig = importlib.import_module("plenum.config")
        try:
            homeDir = os.path.expanduser(homeDir or "~")

            configDir = os.path.join(homeDir, ".plenum")
            config = getInstalledConfig(configDir, "plenum_config.py")

            refConfig.__dict__.update(config.__dict__)
        except FileNotFoundError:
            pass
        refConfig.baseDir = os.path.expanduser(refConfig.baseDir)
        CONFIG = refConfig
    return CONFIG


async def untilTrue(condition, *args, timeout=5) -> bool:
    """
    Keep checking the condition till it is true or a timeout is reached

    :param condition: the condition to check (a function that returns bool)
    :param args: the arguments to the condition
    :return: True if the condition is met in the given timeout, False otherwise
    """
    result = False
    start = time.perf_counter()
    elapsed = 0
    while elapsed < timeout:
        result = condition(*args)
        if result:
            break
        await asyncio.sleep(.1)
        elapsed = time.perf_counter() - start
    return result


def hasKeys(data, keynames):
    """
    Checks whether all keys are present in the given data, and are not None
    """
    # if all keys in `keynames` are not present in `data`
    if len(set(keynames).difference(set(data.keys()))) != 0:
        return False
    for key in keynames:
        if data[key] is None:
            return False
    return True


def firstKey(d: Dict):
    return next(iter(d.keys()))


def firstValue(d: Dict):
    return next(iter(d.values()))


def seedFromHex(seed):
    if len(seed) == 64:
        try:
            return unhexlify(seed)
        except:
            pass


def cleanSeed(seed=None):
    if seed:
        bts = seedFromHex(seed)
        if not bts:
            if isinstance(seed, str):
                seed = seed.encode('utf-8')
            bts = bytes(seed)
            if len(seed) != 32:
                error('seed length must be 32 bytes')
        return bts


def isHexKey(key):
    try:
        if len(key) == 64 and int(key, 16):
            return True
    except ValueError as ex:
        return False
    except Exception as ex:
        print(ex)
        exit()


def getCryptonym(identifier):
    isHex = isHexKey(identifier)
    return base58.b58encode(unhexlify(identifier.encode())).decode() if isHex \
        else identifier


def hexToFriendly(hx):
    if isinstance(hx, str):
        hx = hx.encode()
    raw = unhexlify(hx)
    return rawToFriendly(raw)


def rawToFriendly(raw):
    return base58.b58encode(raw)


def cryptonymToHex(cryptonym: str) -> bytes:
    return hexlify(base58.b58decode(cryptonym.encode()))


def runWithLoop(loop, callback, *args, **kwargs):
    if loop.is_running():
        loop.call_soon(asyncio.async, callback(*args, **kwargs))
    else:
        loop.run_until_complete(callback(*args, **kwargs))


def checkIfMoreThanFSameItems(items, maxF):
    jsonifiedItems = [json.dumps(item, sort_keys=True) for item in items]
    counts = {}
    for jItem in jsonifiedItems:
        counts[jItem] = counts.get(jItem, 0) + 1
    if counts[max(counts, key=counts.get)] > maxF:
        return json.loads(max(counts, key=counts.get))
    else:
        return False


def friendlyEx(ex: Exception) -> str:
    curEx = ex
    friendly = ""
    end = ""
    while curEx:
        if len(friendly):
            friendly += " [caused by "
            end += "]"
        friendly += "{}".format(curEx)
        curEx = curEx.__cause__
    friendly += end
    return friendly


def updateFieldsWithSeqNo(fields):
    r = OrderedDict()
    r[F.seqNo.name] = (str, int)
    r.update(fields)
    return r


def bootstrapClientKeys(identifier, verkey, nodes):
    # bootstrap client verification key to all nodes
    for n in nodes:
        n.clientAuthNr.addClient(identifier, verkey)


def prettyDate(time=False):
    """
    Get a datetime object or a int() Epoch timestamp and return a
    pretty string like 'an hour ago', 'Yesterday', '3 months ago',
    'just now', etc
    """
    from datetime import datetime
    now = datetime.now()
    if time is None:
        return None

    if not isinstance(time, (int, datetime)):
        raise RuntimeError("Cannot parse time")
    if isinstance(time,int):
        diff = now - datetime.fromtimestamp(time)
    elif isinstance(time, datetime):
        diff = now - time
    else:
        diff = now - now
    second_diff = diff.seconds
    day_diff = diff.days

    if day_diff < 0:
        return ''

    if day_diff == 0:
        if second_diff < 10:
            return "just now"
        if second_diff < 60:
            return str(second_diff) + " seconds ago"
        if second_diff < 120:
            return "a minute ago"
        if second_diff < 3600:
            return str(int(second_diff / 60)) + " minutes ago"
        if second_diff < 7200:
            return "an hour ago"
        if second_diff < 86400:
            return str(int(second_diff / 3600)) + " hours ago"
    if day_diff == 1:
        return "Yesterday"
    if day_diff < 7:
        return str(day_diff) + " days ago"
