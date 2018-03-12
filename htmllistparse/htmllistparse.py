#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import collections
import urllib.parse

import bs4

RE_ISO8601 = re.compile(r'\d{4}-\d+-\d+T\d+:\d{2}:\d{2}Z')
DATETIME_FMTs = (
(re.compile(r'\d+-[A-S][a-y]{2}-\d{4} \d+:\d{2}:\d{2}'), "%d-%b-%Y %H:%M:%S"),
(re.compile(r'\d+-[A-S][a-y]{2}-\d{4} \d+:\d{2}'), "%d-%b-%Y %H:%M"),
(re.compile(r'\d{4}-\d+-\d+ \d+:\d{2}:\d{2}'), "%Y-%m-%d %H:%M:%S"),
(RE_ISO8601, "%Y-%m-%dT%H:%M:%SZ"),
(re.compile(r'\d{4}-\d+-\d+ \d+:\d{2}'), "%Y-%m-%d %H:%M"),
(re.compile(r'\d{4}-[A-S][a-y]{2}-\d+ \d+:\d{2}:\d{2}'), "%Y-%b-%d %H:%M:%S"),
(re.compile(r'\d{4}-[A-S][a-y]{2}-\d+ \d+:\d{2}'), "%Y-%b-%d %H:%M"),
(re.compile(r'[F-W][a-u]{2} [A-S][a-y]{2} +\d+ \d{2}:\d{2}:\d{2} \d{4}'), "%a %b %d %H:%M:%S %Y"),
(re.compile(r'[F-W][a-u]{2}, \d+ [A-S][a-y]{2} \d{4} \d{2}:\d{2}:\d{2} .+'), "%a, %d %b %Y %H:%M:%S %Z"),
(re.compile(r'\d{4}-\d+-\d+'), "%Y-%m-%d"),
(re.compile(r'\d+/\d+/\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}'), "%d/%m/%Y %H:%M:%S %z"),
(re.compile(r'\d{2} [A-S][a-y]{2} \d{4}'), "%d %b %Y")
)

RE_FILESIZE = re.compile(r'\d+(\.\d+)? ?[BKMGTPEZY]|\d+|-', re.I)
RE_ABSPATH = re.compile(r'^((ht|f)tps?:/)?/')
RE_COMMONHEAD = re.compile('Name|(Last )?modifi(ed|cation)|date|Size|Description|Metadata|Type|Parent Directory', re.I)
RE_HASTEXT = re.compile('.+')
RE_HEAD_NAME = re.compile('name$|^file|^download')
RE_HEAD_MOD = re.compile('modifi|^uploaded|date|time')
RE_HEAD_SIZE = re.compile('size|bytes$')

FileEntry = collections.namedtuple('FileEntry', 'name modified size description')

def human2bytes(s):
    """
    >>> human2bytes('1M')
    1048576
    >>> human2bytes('1G')
    1073741824
    """
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        symbols = 'BKMGTPEZY'
        letter = s[-1:].strip().upper()
        num = float(s[:-1])
        prefix = {symbols[0]: 1}
        for i, s in enumerate(symbols[1:]):
            prefix[s] = 1 << (i+1)*10
        return int(num * prefix[letter])

def aherf2filename(a_href):
    isdir = ('/' if a_href[-1] == '/' else '')
    return os.path.basename(urllib.parse.unquote(a_href.rstrip('/'))) + isdir

def parse(soup):
    '''
    Try to parse apache/nginx-style directory listing with all kinds of tricks.

    Exceptions or an empty listing suggust a failure.
    We strongly recommend generating the `soup` with 'html5lib'.

    Returns: Current directory, Directory listing
    '''
    cwd = None
    listing = []
    if soup.title and soup.title.string and soup.title.string.startswith('Index of '):
        cwd = soup.title.string[9:]
    elif soup.h1:
        title = soup.h1.get_text().strip()
        if title.startswith('Index of '):
            cwd = title[9:]
    [img.decompose() for img in soup.find_all('img')]
    file_name = file_mod = file_size = file_desc = None
    pres = [x for x in soup.find_all('pre') if
            x.find('a', string=RE_HASTEXT)]
    tables = [x for x in soup.find_all('table') if
              x.find(string=RE_COMMONHEAD)] if not pres else ()
    heads = []
    if pres:
        pre = pres[0]
        started = False
        for element in (pre.hr.next_siblings if pre.hr else pre.children):
            if element.name == 'a':
                if not element.string or not element.string.strip():
                    continue
                elif started:
                    if file_name:
                        listing.append(FileEntry(
                            file_name, file_mod, file_size, file_desc))
                    file_name = aherf2filename(element['href'])
                    file_mod = file_size = file_desc = None
                elif (element.string in ('Parent Directory', '..', '../') or
                      element['href'][0] not in '?/'):
                    started = True
            elif not element.name:
                line = element.string.replace('\r', '').split('\n', 1)[0].lstrip()
                for regex, fmt in DATETIME_FMTs:
                    match = regex.match(line)
                    if match:
                        file_mod = time.strptime(match.group(0), fmt)
                        line = line[match.end():].lstrip()
                        break
                match = RE_FILESIZE.match(line)
                if match:
                    sizestr = match.group(0)
                    if sizestr == '-':
                        file_size = None
                    else:
                        file_size = human2bytes(sizestr.replace(' ', '').replace(',', ''))
                    line = line[match.end():].lstrip()
                if line:
                    file_desc = line.rstrip()
                    if file_name and file_desc == '/':
                        file_name += '/'
                        file_desc = None
            else:
                continue
        if file_name:
            listing.append(FileEntry(file_name, file_mod, file_size, file_desc))
    elif tables:
        started = False
        for tr in tables[0].find_all('tr'):
            status = 0
            file_name = file_mod = file_size = file_desc = None
            if started:
                if tr.parent.name in ('thead', 'tfoot') or tr.th:
                    continue
                for td in tr.find_all('td'):
                    if status >= len(heads):
                        raise AssertionError("can't detect table column number")
                    if td.get('colspan'):
                        continue
                    elif heads[status] == 'name':
                        if not td.a:
                            continue
                        a_str = td.a.get_text().strip()
                        a_href = td.a['href']
                        if not a_str or not a_href or a_href[0] == '#':
                            continue
                        elif a_str == 'Parent Directory' or a_href == '../':
                            break
                        else:
                            file_name = aherf2filename(a_href)
                            status = 1
                    elif heads[status] == 'modified':
                        if td.time:
                            timestr = td.time.get('datetime', '')
                            if RE_ISO8601.match(timestr):
                                file_mod = time.strptime(timestr, "%Y-%m-%dT%H:%M:%SZ")
                                status += 1
                                continue
                        timestr = td.get_text().strip()
                        if timestr:
                            for regex, fmt in DATETIME_FMTs:
                                if regex.match(timestr):
                                    file_mod = time.strptime(timestr, fmt)
                                    break
                            else:
                                if td.get('data-sort-value'):
                                    file_mod = time.gmtime(int(td['data-sort-value']))
                                # else:
                                    # raise AssertionError(
                                        # "can't identify date/time format")
                        status += 1
                    elif heads[status] == 'size':
                        sizestr = td.get_text().strip().replace(',', '')
                        if sizestr == '-' or not sizestr:
                            file_size = None
                        elif td.get('data-sort-value'):
                            file_size = int(td['data-sort-value'])
                        else:
                            match = RE_FILESIZE.match(sizestr)
                            if match:
                                file_size = human2bytes(
                                    match.group(0).replace(' ', ''))
                            else:
                                file_size = None
                        status += 1
                    elif heads[status] == 'description':
                        file_desc = file_desc or ''.join(map(str, td.children)
                                        ).strip(' \t\n\r\x0b\x0c\xa0') or None
                        status += 1
                    elif status:
                        # unknown header
                        status += 1
                if file_name:
                    listing.append(FileEntry(
                        file_name, file_mod, file_size, file_desc))
            elif tr.hr:
                started = True
                continue
            elif tr.find(string=RE_COMMONHEAD):
                namefound = False
                colspan = False
                for th in (tr.find_all('th') if tr.th else tr.find_all('td')):
                    if th.get('colspan'):
                        colspan = True
                        continue
                    name = th.get_text().strip(' \t\n\r\x0b\x0c\xa0↑↓').lower()
                    if not name:
                        continue
                    elif not namefound and RE_HEAD_NAME.search(name):
                        heads.append('name')
                        namefound = True
                    elif name in ('size', 'description'):
                        heads.append(name)
                    elif RE_HEAD_MOD.search(name):
                        heads.append('modified')
                    elif RE_HEAD_SIZE.search(name):
                        heads.append('size')
                    elif name.endswith('signature'):
                        heads.append('signature')
                    else:
                        heads.append('description')
                if colspan:
                    continue
                if not heads:
                    heads = ('name', 'modified', 'size', 'description')
                elif not namefound:
                    heads[0] = 'name'
                started = True
                continue
    elif soup.ul:
        for li in soup.ul.find_all('li'):
            a = li.a
            if not a or not a.get('href'):
                continue
            file_name = urllib.parse.unquote(a['href'])
            if (file_name in {'Parent Directory', '.', './', '..', '../', '#'}
                or RE_ABSPATH.match(file_name)):
                continue
            else:
                listing.append(FileEntry(file_name, None, None, None))
    return cwd, listing

def fetch_listing(url, timeout=30):
    import requests
    req = requests.get(url, timeout=timeout)
    req.raise_for_status()
    soup = bs4.BeautifulSoup(req.content, 'html5lib')
    return parse(soup)

if __name__ == '__main__':
    import sys
    import requests
    for url in sys.argv[1:] or ('http://httpredir.debian.org/debian/',):
        req = requests.get(url, timeout=30)
        req.raise_for_status()
        print(req.url)
        soup = bs4.BeautifulSoup(req.content, 'html5lib')
        cwd, listing = parse(soup)
        print('Cwd:', cwd)
        for f in listing:
            print(f)
        print()
