from setuptools import setup
import sys

exec(open("trio_asyncio/_version.py", encoding="utf-8").read())

LONG_DESC = """\
``trio-asyncio`` is a re-implementation of the ``asyncio`` mainloop on top of
Trio.

Rationale
=========

There are quite a few asyncio-compatible libraries.

On the other hand, Trio has native concepts of tasks and task cancellation.
Asyncio, on the other hand, is based on chaining Future objects, albeit
with nicer syntax.

Thus, being able to use asyncio libraries from Trio is useful.

Principle of operation
======================

The core of the "normal" asyncio main loop is the repeated execution of
synchronous code that's submitted to ``call_soon`` or
``add_reader``/``add_writer``.

Everything else within ``asyncio``, i.e. Futures and ``async``/``await``,
is just syntactic sugar. There is no concept of a task; while a Future can
be cancelled, that in itself doesn't affect the code responsible for
fulfilling it.

On the other hand, trio has genuine tasks with no separation between
returning a value asynchronously, and the code responsible for providing
that value.

``trio_asyncio`` implements a task which runs (its own version of) the
asyncio main loop. It also contains shim code which translates between these
concepts as transparently and correctly as possible, and it supplants a few
of the standard loop's key functions.

This works rather well: ``trio_asyncio`` consists of just ~700 lines of
code (asyncio: ~8000) but passes the complete Python 3.6 test suite with no
errors.

``trio_asyncio`` requires Python 3.6 or better.

Author
======

Matthias Urlichs <matthias@urlichs.de>

"""

install_requires = [
    "trio >= 0.18.0",
    "outcome",
    "sniffio",
]
if sys.version_info < (3, 7):
    install_requires.append("contextvars >= 2.1")
    install_requires.append("async_generator >= 1.6")

setup(
    name="trio_asyncio",
    version=__version__,  # noqa: F821
    description="A re-implementation of the asyncio mainloop on top of Trio",
    long_description=LONG_DESC,
    author="Matthias Urlichs",
    author_email="matthias@urlichs.de",
    url="https://github.com/python-trio/trio-asyncio",
    license="MIT -or- Apache License 2.0",
    packages=["trio_asyncio"],
    install_requires=install_requires,
    # This means, just install *everything* you see under trio/, even if it
    # doesn't look like a source file, so long as it appears in MANIFEST.in:
    include_package_data=True,
    python_requires=">=3.7",  # temporary, for RTD
    keywords=["async", "io", "trio", "asyncio", "trio-asyncio"],
    setup_requires=['pytest-runner'],
    tests_require=['pytest >= 5.4', 'pytest-trio >= 0.6', 'outcome'],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: BSD",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: System :: Networking",
        "Framework :: Trio",
        "Framework :: AsyncIO",
    ],
)
