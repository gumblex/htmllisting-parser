# htmllisting-parser
Python parser for Apache/nginx-style HTML directory listing

```python3
import htmllistparse
cwd, listing = htmllistparse.fetch_listing(some_url)
```

where `cwd` is the current directory, `listing` is a list of `FileEntry` named tuples:

* `name`: File name, `str`
* `modified`: Last modification time, `time.struct_time` or `None`. Timezone is not known.
* `size`: File size, `int` or `None`. May be estimated from the prefiex, such as "K", "M".
* `description`: File description, file type, or any other things found. `str` as HTML, or `None`.
