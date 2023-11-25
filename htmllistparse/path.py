import pathlib as _pathlib
import posixpath as _poxis
import uritools as _uri
import typing as _ty
import requests as _req
import bs4 as _bs4
import io as _io

from .utils import FileStat, parsedate
from .htmllistparse import parse


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


class HttpPath(PureUriPath):
    __slots__ = ()

    def _dirls_(self, session: _req.Session, **requests_args):
        req = session.get(self.as_uri(), **requests_args)
        req.raise_for_status()
        soup = _bs4.BeautifulSoup(req.content, "html5lib")
        _, listing = parse(soup)
        return listing

    def iterdir(self, session: _req.Session = None, **requests_args):
        session = session or _req.Session()
        for child in self._dirls_(session, **requests_args):
            path = self / child.name
            yield path

    def stat(
        self, *, follow_symlinks=True, session: _req.Session = None, **requests_args
    ):
        session = session or _req.Session()
        url = self.as_uri()
        req = session.head(url, **requests_args, allow_redirects=False)
        req.close()
        is_dir = False
        if req.status_code == 404:
            raise FileNotFoundError(url)
        elif req.status_code == 403:
            raise PermissionError(url)
        elif req.status_code in (301, 302):
            is_dir = True
        else:
            req.raise_for_status()
        st_size = int(req.headers.get("Content-Length", 0))
        lm = req.headers.get("Last-Modified")
        if lm is None:
            parent = self.parent
            if self != parent:
                try:
                    entry = next(
                        filter(
                            lambda p: p.name == self.name,
                            parent._dirls_(session, **requests_args),
                        )
                    )
                    if entry and entry.modified:
                        lm = entry.modified
                except:
                    pass

        return FileStat(st_size=st_size, st_mtime=parsedate(lm), is_dir=is_dir)

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
        session = session or _req.Session()
        requests_args = requests_args or {}
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

    def read_bytes(self):
        """
        Open the file in bytes mode, read it, and close the file.
        """
        with self.open(mode="rb") as f:
            return f.read()

    def read_text(self, encoding=None, errors=None):
        with self.open(mode="r", encoding=encoding, errors=errors) as f:
            return f.read()
