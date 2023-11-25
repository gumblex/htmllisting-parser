import pathlib as _pathlib
import posixpath as _poxis
import uritools as _uri
import typing as _ty
import requests as _req
import io as _io
import copy as _cp
import stat as _stat

from .utils import FileStat, parsedate, ls
from .htmllistparse import FileEntry


class PureUriPath(_pathlib.PurePath):
    _flavour = _poxis
    __slots__ = ()

    @property
    def scheme(self):
        return self.drive.split("://", maxsplit=1)[0]

    @property
    def authority(self):
        return self.drive.split("://", maxsplit=1)[1]

    @classmethod
    def _parse_path(cls, path: str) -> _ty.Tuple[str, str, str, list[str]]:
        parts = _uri.urisplit(path)
        scheme: str = parts.scheme
        authority: str = parts.authority
        _, root, parsed = super()._parse_path(parts.path)
        return scheme + "://" + authority, root, parsed

    @classmethod
    def _format_parsed_parts(cls, drv: str, root: str, tail: _ty.List[str]) -> str:
        scheme, authority = drv.split("://", maxsplit=1)
        return _uri.uricompose(
            scheme=scheme, authority=authority, path=(root or "") + "/".join(tail)
        )

    def as_uri(self):
        return str(self)


class UriPath(PureUriPath):
    __slots__ = ()

    def _dirls_(self) -> _ty.Iterator[FileEntry]:
        raise NotImplementedError("dirls")

    def iterdir(self):
        for child in self._dirls_():
            path = self / child.name
            yield path

    def iterdir_ext(self, recursive=False):
        for child in self.iterdir():
            yield child
            if recursive and child.is_dir():
                yield from child.iterdir_ext(True)

    def stat(self, follow_symlinks=False) -> FileStat:
        raise NotImplementedError()

    def is_dir(self, follow_symlinks=False):
        return self.stat(follow_symlinks).st_mode & _stat.S_IFDIR

    def is_file(self, follow_symlinks=False):
        return self.stat(follow_symlinks).st_mode & _stat.S_IFREG

    def open(
        self,
        mode="r",
        buffering=-1,
        encoding=None,
        errors=None,
        newline=None,
        session: _req.Session = None,
        requests_args=None,
    ) -> _io.IOBase:
        raise NotImplementedError()

    def read_bytes(self):
        """
        Open the file in bytes mode, read it, and close the file.
        """
        with self.open(mode="rb") as f:
            return f.read()

    def read_text(self, encoding=None, errors=None):
        with self.open(mode="r", encoding=encoding, errors=errors) as f:
            return f.read()

    def exists(self, *, follow_symlinks=True):
        try:
            self.stat()
            return True
        except FileNotFoundError:
            return False

    def walk(self, top_down=True, on_error=None, follow_symlinks=False):
        """Walk the directory tree from this directory, similar to os.walk()."""
        paths: "list[UriPath|tuple[UriPath, list[str], list[str]]]" = [self]

        while paths:
            path = paths.pop()
            if isinstance(path, tuple):
                yield path
                continue

            # We may not have read permission for self, in which case we can't
            # get a list of the files the directory contains. os.walk()
            # always suppressed the exception in that instance, rather than
            # blow up for a minor reason when (say) a thousand readable
            # directories are still left to visit. That logic is copied here.
            try:
                scandir_it = path.iterdir()
            except OSError as error:
                if on_error is not None:
                    on_error(error)
                continue

            dirnames:'list[str]' = []
            filenames:'list[str]' = []
            for entry in scandir_it:
                try:
                    is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                except OSError:
                    # Carried over from os.path.isdir().
                    is_dir = False

                if is_dir:
                    dirnames.append(entry.name)
                else:
                    filenames.append(entry.name)

            if top_down:
                yield path, dirnames, filenames
            else:
                paths.append((path, dirnames, filenames))

            paths += [path / d for d in reversed(dirnames)]


class HttpPath(UriPath):
    __slots__ = ("_isdir", "_session", "_requests_args")
    _isdir: bool
    _session: _req.Session
    _requests_args: dict

    def __new__(cls, *args, **kwargs):
        r = super().__new__(cls, *args, **kwargs)
        r._isdir = None
        r._session = _req.Session()
        r._requests_args = {}
        return r

    @property
    def parent(self):
        p: HttpPath = super().parent
        p._session = self._session
        p._requests_args = self._requests_args
        return p

    def _dirls_(self):
        return ls(self.as_uri(), self._session, **self._requests_args)

    def iterdir(self):
        for child in self._dirls_():
            path = self / child.name
            path._isdir = child.name.endswith("/")
            yield path

    def stat(self, *, follow_symlinks=True):
        session = self._session
        url = self.as_uri()
        req = session.head(url, **self._requests_args, allow_redirects=False)
        req.close()
        entry = None
        if self._isdir is None:
            self._isdir = req.status_code in (301, 302) or self._flavour.join(
                self._raw_paths
            ).endswith("/")
        if req.status_code == 404:
            raise FileNotFoundError(url)
        elif req.status_code == 403:
            raise PermissionError(url)
        elif req.status_code in (301, 302):
            pass
        else:
            req.raise_for_status()
        st_size = int(req.headers.get("Content-Length", 0))
        lm = req.headers.get("Last-Modified")
        if lm is None:
            parent = self.parent
            if self.parts[-1] != parent.parts[-1]:
                try:
                    entry = next(
                        filter(
                            lambda p: p.name == self.name,
                            parent._dirls_(),
                        )
                    )
                    if entry and entry.modified:
                        lm = entry.modified
                except:
                    pass

        return FileStat(st_size=st_size, st_mtime=parsedate(lm), is_dir=self._isdir)

    def open(
        self,
        mode="r",
        buffering=-1,
        encoding=None,
        errors=None,
        newline=None,
        session: _req.Session = None,
        requests_args=None,
    ):
        buffer_size = _io.DEFAULT_BUFFER_SIZE if buffering <= 0 else buffering
        session = session or self._session
        requests_args = requests_args or self._requests_args
        binary_mode = "b" in mode
        req = session.get(self.as_uri(), **requests_args, stream=True)
        buffer = (
            _io.BytesIO() if binary_mode else _io.StringIO()
        )  # TODO Write actual async code instead of reading it all
        if not binary_mode:
            req.encoding = encoding or "utf-8"

        for b in req.iter_content(
            chunk_size=buffer_size, decode_unicode=not binary_mode
        ):
            buffer.write(b)
        buffer.seek(0)
        return buffer

    def is_dir(self, follow_symlinks=False):
        if self._isdir is None:
            self.stat()
        return self._isdir

    def is_file(self, follow_symlinks=False):
        return not self.is_dir()

    def with_segments(self, *pathsegments):
        r = super().with_segments(*pathsegments)
        session = self._session
        args = self._requests_args
        for p in reversed(pathsegments):
            if isinstance(p, HttpPath):
                session = p._session
                args = p._requests_args
                break
        r._session = session
        r._requests_args = _cp.deepcopy(args)
        return r

    def with_session(self, session: _req.Session, **requests_args):
        r = HttpPath(self)
        r._session = session
        r._requests_args = requests_args
