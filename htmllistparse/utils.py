import stat as _stat
import typing as _ty
import time as _time
from email.utils import parsedate as _parsedate
import bs4 as _bs4
from .htmllistparse import parse

if _ty.TYPE_CHECKING:
    import requests

def ls(url, session: 'requests.Session', **requests_args):
    req = session.get(url, **requests_args)
    req.raise_for_status()
    soup = _bs4.BeautifulSoup(req.content, "html5lib")
    _, listing = parse(soup)
    return listing

def parsedate(date: _ty.Union[str, _time.struct_time, tuple, float]):
    if date is None:
        return _time.time()
    if isinstance(date, str):
        date = _parsedate(date)
    return _time.mktime(date)


def sizeof_fmt(num: _ty.Union[int, float]):
    for unit in ("", "K", "M", "G", "T", "P", "E", "Z"):
        if abs(num) < 1024:
            if unit:
                return "%3.1f%s" % (num, unit)
            else:
                return int(num)
        num /= 1024.0
    return "%.1f%s" % (num, "Y")


class FileStat:
    __slots__ = (
        "st_mode",
        "st_nlink",
        "st_uid",
        "st_gid",
        "st_size",
        "st_atime",
        "st_mtime",
        "st_ctime",
    )

    def __init__(
        self,
        st_mode: int = None,
        st_size: int = 0,
        st_mtime: int = 0,
        is_dir: bool = False,
    ):
        self.st_mode = st_mode or (
            _stat.S_IFDIR | 0o555 if is_dir else _stat.S_IFREG | 0o444
        )
        self.st_nlink = 1
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = st_size
        self.st_atime = 0
        self.st_mtime = st_mtime
        self.st_ctime = 0

    def settime(self, value):
        self.st_atime = self.st_mtime = self.st_ctime = value

    def setmode(self, value, isdir=None):
        if isdir is None:
            isdir = self.st_mode & _stat.S_IFDIR
        if isdir:
            self.st_mode = _stat.S_IFDIR | value
        else:
            self.st_mode = _stat.S_IFREG | value

    def __getitem__(self, key):
        return getattr(self, key)

    def items(self):
        for key in self.__slots__:
            yield key, getattr(self, key)

    def __repr__(self):
        return "<FileStat mode=%o, size=%s, mtime=%d>" % (
            self.st_mode,
            sizeof_fmt(self.st_size),
            self.st_mtime,
        )
