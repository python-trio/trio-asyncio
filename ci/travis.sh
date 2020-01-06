#!/bin/bash

set -ex

# See https://github.com/python-trio/trio/issues/334
YAPF_VERSION=0.20.0

if [ "$TRAVIS_OS_NAME" = "osx" ]; then
    curl -Lo macpython.pkg https://www.python.org/ftp/python/${MACPYTHON}/python-${MACPYTHON}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /
    ls /Library/Frameworks/Python.framework/Versions/*/bin/
    PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/*/bin/python3
    sudo $PYTHON_EXE -m pip install virtualenv
    $PYTHON_EXE -m virtualenv testenv
    source testenv/bin/activate
fi

if [ "$USE_PYPY_NIGHTLY" = "1" ]; then
    curl -fLo pypy.tar.bz2 http://buildbot.pypy.org/nightly/py3.5/pypy-c-jit-latest-linux64.tar.bz2
    if [ ! -s pypy.tar.bz2 ]; then
        # We know:
        # - curl succeeded (200 response code; -f means "exit with error if
        # server returns 4xx or 5xx")
        # - nonetheless, pypy.tar.bz2 does not exist, or contains no data
        # This isn't going to work, and the failure is not informative of
        # anything involving this package.
        ls -l
        echo "PyPy3 nightly build failed to download – something is wrong on their end."
        echo "Skipping testing against the nightly build for right now."
        exit 0
    fi
    tar xaf pypy.tar.bz2
    # something like "pypy-c-jit-89963-748aa3022295-linux64"
    PYPY_DIR=$(echo pypy-c-jit-*)
    PYTHON_EXE=$PYPY_DIR/bin/pypy3
    ($PYTHON_EXE -m ensurepip \
     && $PYTHON_EXE -m pip install virtualenv \
     && $PYTHON_EXE -m virtualenv testenv) \
        || (echo "pypy nightly is broken; skipping tests"; exit 0)
    source testenv/bin/activate
fi

if [ "$USE_PYPY_RELEASE_VERSION" != "" ]; then
    curl -fLo pypy.tar.bz2 https://bitbucket.org/squeaky/portable-pypy/downloads/pypy3.5-${USE_PYPY_RELEASE_VERSION}-linux_x86_64-portable.tar.bz2
    tar xaf pypy.tar.bz2
    # something like "pypy3.5-5.7.1-beta-linux_x86_64-portable"
    PYPY_DIR=$(echo pypy3.5-*)
    PYTHON_EXE=$PYPY_DIR/bin/pypy3
    $PYTHON_EXE -m ensurepip
    $PYTHON_EXE -m pip install virtualenv
    $PYTHON_EXE -m virtualenv testenv
    source testenv/bin/activate
fi

pip install -U pip setuptools wheel

if [ "$CHECK_FORMATTING" = "1" ]; then
    pip install yapf==${YAPF_VERSION}
    if ! yapf -rpd setup.py trio_asyncio; then
        cat <<EOF
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Formatting problems were found (listed above). To fix them, run

   pip install yapf==${YAPF_VERSION}
   yapf -rpi setup.py trio_asyncio

in your local checkout.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
EOF
        exit 1
    fi
    exit 0
fi

python setup.py sdist --formats=zip
pip install dist/*.zip

if [ "$CHECK_DOCS" = "1" ]; then
    pip install -Ur ci/rtd-requirements.txt
    cd docs
    # -n (nit-picky): warn on missing references
    # -W: turn warnings into errors
    sphinx-build -nW  -b html source build
else
    # Actual tests
    pip install -Ur ci/test-requirements.txt

    mkdir empty
    cd empty

    pytest -ra -v --cov=trio_asyncio --cov-config=../.coveragerc --verbose ../tests

    bash <(curl -s https://codecov.io/bash)
fi
