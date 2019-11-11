#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import stat
import time
import logging
import argparse
import calendar
import urllib.parse
from errno import EACCES, ENOENT, EIO
from email.utils import parsedate

import bs4
import requests
import htmllistparse
try:
    import fusepy as fuse
except ImportError:
    import fuse

CONFIG = {
    'timeout': None,
    'user_agent': None,
}
SESSION = requests.Session()
CONTENT_CHUNK_SIZE = 10 * 1024


def parse_dir(html):
    return htmllistparse.parse(bs4.BeautifulSoup(html, 'html5lib'))


def make_url(urlbase, name):
    return urllib.parse.urljoin(urlbase, urllib.parse.quote(name.lstrip('/')))


def sizeof_fmt(num):
    for unit in ('', 'K', 'M', 'G', 'T', 'P', 'E', 'Z'):
        if abs(num) < 1024:
            if unit:
                return "%3.1f%s" % (num, unit)
            else:
                return int(num)
        num /= 1024.0
    return "%.1f%s" % (num, 'Y')


def convert_fuse_options(options):
    kwargs = {}
    if options is not None:
        for opt in options.split(','):
            kv = opt.split('=', 1)
            if len(kv) == 1:
                kwargs[kv[0]] = True
            else:
                kwargs[kv[0]] = kv[1]
    return kwargs


class IsADirectory(ValueError):
    pass


class FileStat:
    __slots__ = (
        'st_mode', 'st_nlink', 'st_uid', 'st_gid', 'st_size',
        'st_atime', 'st_mtime', 'st_ctime'
    )

    def __init__(self):
        self.st_mode = stat.S_IFREG | 0o444
        self.st_nlink = 1
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = 0
        self.st_atime = 0
        self.st_mtime = 0
        self.st_ctime = 0

    def settime(self, value):
        self.st_atime = self.st_mtime = self.st_ctime = value

    def setmode(self, value, isdir=False):
        if isdir:
            self.st_mode = stat.S_IFDIR | value
        else:
            self.st_mode = stat.S_IFREG | value

    def __getitem__(self, key):
        return getattr(self, key)

    def items(self):
        for key in self.__slots__:
            yield key, getattr(self, key)

    def __repr__(self):
        return '<FileStat mode=%o, size=%s, mtime=%d>' % (
            self.st_mode, sizeof_fmt(self.st_size), self.st_mtime)


class File(io.IOBase):
    __slots__ = (
        'baseurl', 'path', 'url', 'stat', 'init',
        'exist', '_readable', '_seekable', 'offset'
    )

    def __init__(self, baseurl, path):
        self.baseurl = baseurl
        self.path = path
        self.url = make_url(baseurl, path)
        self.stat = FileStat()
        self.init = 0
        self.exist = True
        self._readable = True
        self._seekable = False
        self.offset = 0

    def get_stat(self):
        req = SESSION.head(self.url, timeout=CONFIG[
                           'timeout'], allow_redirects=False)
        req.close()
        if 400 <= req.status_code <= 499:
            self.stat.setmode(0o000)
            self.init = 2
            self._readable = False
            if req.status_code == 404:
                self.exist = False
            return self.stat
        elif req.status_code in (301, 302):
            raise IsADirectory()
        else:
            req.raise_for_status()
        self.stat.st_size = int(req.headers.get('Content-Length', 0))
        lm = req.headers.get('Last-Modified')
        if lm:
            self.stat.settime(time.mktime(parsedate(lm)))
        else:
            self.stat.settime(time.time())
        if req.headers.get('Accept-Ranges') == 'bytes':
            self._seekable = True
        self.init = 2
        return self.stat

    def read(self, size=None, offset=None):
        if not self.init or not self.stat.st_size:
            self.get_stat()
        if not self.exist:
            raise fuse.FuseOSError(ENOENT)
        elif not self.readable():
            raise fuse.FuseOSError(EIO)
        if offset is None:
            offset = self.offset
        end = min(self.stat.st_size, offset + size - 1)
        brange = '%d-%d' % (offset, end)
        headers = {'range': 'bytes=' + brange}
        req = SESSION.get(self.url, headers=headers,
                          stream=True, timeout=CONFIG['timeout'])
        if req.status_code == 206:
            self._seekable = True
        elif req.status_code == 416:
            # we may have a wrong size
            self.get_stat()
            raise fuse.FuseOSError(EIO)
        elif req.status_code == 200:
            self._seekable = False
            if offset != 0:
                raise fuse.FuseOSError(EIO)
        elif req.status_code == 403:
            self._readable = False
            raise fuse.FuseOSError(EACCES)
        elif req.status_code == 404:
            self.exist = False
            self._readable = False
            raise fuse.FuseOSError(ENOENT)
        else:
            self._readable = False
            raise fuse.FuseOSError(EIO)
        content = bytes()
        for chunk in req.iter_content(CONTENT_CHUNK_SIZE, False):
            content += chunk
            if len(content) > size:
                content = content[:size]
                break
        req.close()
        if self._seekable:
            self.offset = end
        return content

    def readable(self):
        return self._readable

    def seekable(self):
        return self._seekable

    def seek(self, offset):
        if self._seekable:
            self.offset = offset

    def tell(self):
        return self.offset


class Directory:
    __slots__ = (
        'baseurl', 'path', 'url', 'stat', 'content', 'init', 'exist', '_readable'
    )

    def __init__(self, baseurl, path):
        self.baseurl = baseurl
        self.path = path
        self.url = make_url(baseurl, path)
        self.stat = FileStat()
        self.stat.setmode(0o555, True)
        self.stat.st_nlink = 2
        self.content = ['.', '..']
        self.init = 0
        self.exist = True
        self._readable = True

    def read(self):
        req = SESSION.get(self.url, timeout=CONFIG['timeout'])
        try:
            req.raise_for_status()
        except requests.exceptions.HTTPError:
            self.stat.setmode(0o000, True)
            self.init = 2
            self._readable = False
            if req.status_code == 403:
                raise fuse.FuseOSError(EACCES)
            elif req.status_code == 404:
                self.exist = False
                raise fuse.FuseOSError(ENOENT)
            else:
                raise fuse.FuseOSError(EIO)
        lm = req.headers.get('Last-Modified')
        if lm:
            self.stat.settime(time.mktime(parsedate(lm)))
        else:
            self.stat.settime(time.time())
        try:
            cwd, listing = parse_dir(req.content)
        except Exception:
            logging.exception('failed to parse listing: ' + self.url)
            listing = []
        content = ['.', '..']
        objmap = {}
        for name, modified, size, description in listing:
            fpath = os.path.join(self.path, name)
            if name[-1] == '/':
                fileobj = Directory(self.baseurl, fpath)
                fpath = fpath.rstrip('/')
            else:
                fileobj = File(self.baseurl, fpath)
                if size is None:
                    fileobj.get_stat()
                else:
                    fileobj.stat.st_size = size
            if modified:
                fileobj.stat.settime(calendar.timegm(modified))
            else:
                fileobj.stat.settime(self.stat.st_mtime)
            fileobj.init = fileobj.init or 1
            content.append(name.rstrip('/'))
            objmap[fpath] = fileobj
        self.content = content
        self.stat.st_nlink = len(content)
        self.init = 2
        self._readable = True
        return objmap

    def readable(self):
        return self._readable


class rehttpfs(fuse.LoggingMixIn, fuse.Operations):
    '''Reinvented HTTP Filesystem'''

    def __init__(self, url):
        self.url = url
        if url[-1] != '/':
            self.url += '/'
        self.fd = 0
        self.metacache = {'/': Directory(self.url, '/')}

    def _getpath(self, path, refresh=False):
        pathobj = self.metacache.get(path)
        if isinstance(pathobj, Directory):
            return self._getdirobj(path, refresh)
        else:
            return self._getfileobj(path, refresh)

    def _makeparents(self, path):
        while path != '/':
            path = os.path.dirname(path)
            if path not in self.metacache:
                self.metacache[path] = Directory(self.url, path + '/')
            else:
                break

    def _getfileobj(self, path, refresh=False):
        logging.debug('_getfileobj: %s', path)
        fileobj = self.metacache.get(path)
        try:
            if fileobj:
                if not fileobj.init or refresh:
                    fileobj.get_stat()
            else:
                self._makeparents(path)
                fileobj = File(self.url, path)
                fileobj.get_stat()
                self.metacache[path] = fileobj
        except IsADirectory:
            logging.info('IsADirectory: %s', path)
            return self._getdirobj(path, refresh)
        return fileobj

    def _getdirobj(self, path, refresh=False):
        logging.debug('_getdirobj: %s', path)
        path = path.rstrip('/')
        dirobj = self.metacache.get(path)
        if dirobj:
            if not dirobj.init or refresh:
                objmap = dirobj.read()
                self._update_metacache(objmap)
        else:
            self._makeparents(path)
            dirobj = Directory(self.url, path + '/')
            objmap = dirobj.read()
            self._update_metacache(objmap)
            self.metacache[path] = dirobj
        return dirobj

    def _update_metacache(self, objmap):
        for name, obj in objmap.items():
            cached = self.metacache.get(name)
            if not (cached and cached.init and type(cached) == type(obj)):
                self.metacache[name] = obj

    def access(self, path, amode):
        if amode & os.W_OK:
            raise fuse.FuseOSError(EACCES)
        obj = self._getpath(path)
        if not obj.exist:
            raise fuse.FuseOSError(ENOENT)
        elif (obj.stat.st_mode & amode) != amode:
            raise fuse.FuseOSError(EACCES)
        return 0

    def getattr(self, path, fh=None):
        logging.debug('getattr: %s', path)
        obj = self._getpath(path)
        if not obj.exist:
            raise fuse.FuseOSError(ENOENT)
        return obj.stat

    def open(self, path, flags):
        self.fd += 1
        return self.fd

    def opendir(self, path):
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        fileobj = self._getfileobj(path, False)
        return fileobj.read(size, offset)

    def readdir(self, path, fh):
        logging.debug('readdir: %s', path)
        dirobj = self._getdirobj(path)
        if dirobj.init != 2:
            objmap = dirobj.read()
            self._update_metacache(objmap)
        content = []
        for name in dirobj.content:
            fpath = os.path.normpath(os.path.join(path, name))
            content.append((name, self.metacache[fpath].stat, 0))
        return content


def main():
    parser = argparse.ArgumentParser(description="Mount HTML directory listings.")
    parser.add_argument("-o", help="comma separated FUSE options", metavar='OPTIONS')
    parser.add_argument("-t", "--timeout", help="HTTP request timeout", type=int, default=30)
    parser.add_argument("-u", "--user-agent", help="HTTP User-Agent")
    parser.add_argument("-v", "--verbose", help="enable debug logging", action='store_true')
    parser.add_argument("-d", "--daemon", help="run in background", action='store_true')
    parser.add_argument("url", help="URL to mount")
    parser.add_argument("mountpoint", help="filesystem mount point")
    args = parser.parse_args()
    logging.basicConfig(
        format='%(levelname)s:%(name)s %(message)s',
        level=logging.DEBUG if args.verbose else logging.INFO
    )
    CONFIG['timeout'] = args.timeout
    CONFIG['user_agent'] = args.user_agent
    fuseobj = fuse.FUSE(
        rehttpfs(args.url),
        args.mountpoint,
        foreground=(not args.daemon),
        **convert_fuse_options(args.o)
    )


if __name__ == '__main__':
    main()
