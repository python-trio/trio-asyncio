Tips
====

To run tests
------------

* Install requirements: ``pip install -r ci/test-requirements.txt``
  (possibly in a virtualenv)

* Actually run the tests: ``PYTHONPATH=. pytest-3 tests``


To run yapf
-----------

* Show what changes yapf wants to make:
  ``yapf3 -rpd setup.py trio_asyncio tests``

* Apply all changes directly to the source tree:
  ``yapf -rpi setup.py trio_asyncio tests``

* Find semantic problems: ``flake8 setup.py trio_asyncio tests``


To make a release
-----------------

* Update the version in ``trio_asyncio/_version.py``

* Run ``towncrier`` to collect your release notes.

* Review your release notes.

* Check everything in.

* Double-check it all works, docs build, etc.

* Upload to PyPI: ``make upload``

* Don't forget to ``git push --tags``.

