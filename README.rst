.. image:: https://img.shields.io/pypi/v/trio-asyncio.svg
   :target: https://pypi.org/project/trio-asyncio
   :alt: Latest PyPI version

.. image:: https://img.shields.io/badge/chat-join%20now-blue.svg
   :target: https://gitter.im/python-trio/general
   :alt: Join chatroom

.. image:: https://img.shields.io/badge/docs-read%20now-blue.svg
   :target: https://trio-asyncio.readthedocs.io/en/latest/?badge=latest
   :alt: Documentation status

.. image:: https://github.com/python-trio/trio-asyncio/actions/workflows/ci.yml/badge.svg
   :target: https://github.com/python-trio/trio-asyncio/actions/workflows/ci.yml
   :alt: Automated test status

.. image:: https://codecov.io/gh/python-trio/trio-asyncio/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/python-trio/trio-asyncio
   :alt: Test coverage


==============
 trio-asyncio
==============

**trio-asyncio** is a re-implementation of the ``asyncio`` mainloop on top of
Trio.

trio-asyncio requires at least Python 3.9. It is tested on recent versions of
3.9 through 3.13.

+++++++++++
 Rationale
+++++++++++

Trio has native concepts of tasks and task cancellation. Asyncio is based
on callbacks and chaining Futures, albeit with nicer syntax, making
handling failures and timeouts fundamentally less reliable, especially in
larger programs. Thus, you *really* want to base your async project on Trio.

On the other hand, there are quite a few asyncio-enhanced libraries. You
*really* don't want to re-invent any wheels in your project.

Thus, being able to use asyncio libraries from Trio is useful.
trio-asyncio enables you to do that and more.

--------------------------------------
 Transparent vs. explicit translation
--------------------------------------

``trio_asyncio`` does not try to magically allow calling ``await
trio_code()`` from asyncio or vice versa. There are multiple reasons for
this; the executive summary is that cross-domain calls can't be made to
work correctly, and any such call is likely to result in an irrecoverable
error. You need to keep your code's ``asyncio`` and ``trio`` domains
rigidly separate.

Fortunately, this is not difficult.

+++++++
 Usage
+++++++

Trio-Asyncio's documentation is too large for a README.

For further information, `see the manual on readthedocs <http://trio-asyncio.readthedocs.io/en/latest/>`_.

++++++++++++++
 Contributing
++++++++++++++

Like Trio, trio-asyncio is licensed under both the MIT and Apache licenses.
Submitting a patch or pull request implies your acceptance of these licenses.

Testing is done with ``pytest``. Test coverage is pretty thorough; please
keep it that way when adding new code.

See the `Trio contributor guide
<https://trio.readthedocs.io/en/stable/contributing.html>`__ for much
more detail on how to get involved.

Contributors are requested to follow our `code of conduct
<https://trio.readthedocs.io/en/stable/code-of-conduct.html>`__ in all
project spaces.

++++++++
 Author
++++++++

Matthias Urlichs <matthias@urlichs.de> originally wrote trio-asyncio.
It is now maintained by the `Trio project <https://github.com/python-trio>`_.
