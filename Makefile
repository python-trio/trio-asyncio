#!/usr/bin/make -f

export PYTHONPATH=$(shell pwd)
PYTHON ?= python3.5
PYTEST:=env PYTHONPATH=$(shell pwd) $(PYTHON) /usr/bin/py.test-3

test:
	python3 setup.py test
t:
	$(PYTEST) -s -x -v
# --cov-report term-missing --cov-config .coveragerc --cov=qbroker.unit --cov=qbroker.proto --assert=plain

update:
	@sh utils/update_boilerplate

pypi:
	python3 setup.py sdist upload
	git tag v$(shell python3 setup.py -V)

upload:	pypi
	git push-all --tags
