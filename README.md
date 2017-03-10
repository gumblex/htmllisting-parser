# htmllisting-parser
Python parser for Apache/nginx-style HTML directory listing

```python
import htmllistparse
cwd, listing = htmllistparse.fetch_listing(some_url)

# or you can get the url and make a BeautifulSoup yourself, then use
# cwd, listing = htmllistparse.parse(soup)
```

where `cwd` is the current directory, `listing` is a list of `FileEntry` named tuples:

* `name`: File name, `str`. Have a trailing / if it's a directory.
* `modified`: Last modification time, `time.struct_time` or `None`. Timezone is not known.
* `size`: File size, `int` or `None`. May be estimated from the prefiex, such as "K", "M".
* `description`: File description, file type, or any other things found. `str` as HTML, or `None`.

Supports:

* Vanilla Apache/nginx/lighttpd/darkhttpd autoindex
* Most `<pre>`-style index
* Many other `<table>`-style index
* `<ul>`-style

# ReHTTPFS
Reinvented HTTP Filesystem.

* Mounts most HTTP file listings with FUSE.
* Gets directory tree and file stats with less overHEAD.
* Supports Range requests.
* Supports Keep-Alive.

```
usage: rehttpfs.py [-h] [-o O] [-v] [-d] url mountpoint

Mount HTML directory listings.

positional arguments:
  url            URL to mount
  mountpoint     filesystem mount point

optional arguments:
  -h, --help     show this help message and exit
  -o OPTIONS     comma seperated FUSE options
  -v, --verbose  enable debug logging
  -d, --daemon   run in background
```
