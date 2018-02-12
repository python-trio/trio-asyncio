Finishing setting up your project
=================================

Thanks for using cookiecutter-trio! This is your project now; you can
customize it however you like. Here's some reminders of things you
might want to do to get started:

* Check this into source control (``git init .; git add .; git
  commit -m "Initial commit"``)

* Add a CODE_OF_CONDUCT.md

* Add a CONTRIBUTING.md

* Search the source tree for COOKIECUTTER-TRIO-TODO to find other
  places to fill in.
* Enable `Read the Docs <https://readthedocs.org>`__. (Note: this
  project contains a ``.readthedocs.yml`` file that should be enough
  to get things working.)

* Set up continuous integration: Currently, this project is set up to
  test on Linux and MacOS using Travis, on Windows using Appveyor, and
  to test on PyPy.

  If that's what you want, then go to Travis and Appveyor and enable
  testing for your repo.

  If that's not what you want, then you can trim the list by modifying
  (or deleting) ``.travis.yml``, ``.appveyor.yml``, ``ci/travis.sh``.

* Enable `Codecov <https://codecov.io>`__ for your repo.

* File bugs or pull requests on `cookiecutter-trio
  <https://github.com/python-trio/cookiecutter-trio>`__ reporting any
  problems or awkwardness you ran into (no matter how small!)

* Delete this checklist once it's no longer useful


Tips
====

To run tests
------------

* Install requirements: ``pip install -r test-requirements.txt``
  (possibly in a virtualenv)

* Actually run the tests: ``pytest trio_asyncio``


To run yapf
-----------

* Show what changes yapf wants to make: ``yapf -rpd setup.py
  trio_asyncio``

* Apply all changes directly to the source tree: ``yapf -rpi setup.py
  trio_asyncio``


To make a release
-----------------

* Update the version in ``trio_asyncio/_version.py``

* Run ``towncrier`` to collect your release notes.

* Review your release notes.

* Check everything in.

* Double-check it all works, docs build, etc.

* Build your sdist and wheel: ``python setup.py sdist bdist_wheel``

* Upload to PyPI: ``twine upload dist/*``

* Use ``git tag`` to tag your version.

* Don't forget to ``git push --tags``.
