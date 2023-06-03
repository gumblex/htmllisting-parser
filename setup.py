#!/usr/bin/env python

import sys
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

if sys.version_info < (3, 3):
    raise NotImplementedError("You need at least Python 3.3.")

setup(
    name='htmllistparse',
    version='0.6.1',
    description='Python parser for Apache/nginx-style HTML directory listing.',
    long_description=open('README.rst', 'r').read(),
    author='Dingyuan Wang',
    author_email='gumblex@aosc.io',
    url='https://github.com/gumblex/htmllisting-parser',
    packages=['htmllistparse'],
    install_requires=[
        'beautifulsoup4',
        'html5lib',
        'requests',
        'fusepy'
    ],
    entry_points = {
        'console_scripts': ['rehttpfs=htmllistparse.rehttpfs:main'],
    },
    license='MIT',
    platforms='any',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Topic :: Internet :: WWW/HTTP',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
    ],
    keywords='apache nginx listing fuse'
)
