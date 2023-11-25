import pathlib as _pathlib
import posixpath as _poxis
import uritools as _uri
import typing as _ty


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