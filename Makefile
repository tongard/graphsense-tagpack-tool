SHELL := /bin/bash
PROJECT := tagpack-tool
VENV := .venv
RELEASE := 'v22.11'
RELEASESEM := 'v1.2.0'

all: format lint test build

test:
	pytest -v -m "not slow" --cov=src

dev:
	 pip install -e .[dev]
	 pre-commit install

test-all:
	pytest --cov=src

install-dev: dev
	pip install -e .

install:
	pip install .

lint:
	flake8 tests src

format:
	isort --profile black src
	black tests src

docs:
	tox -e docs

docs-latex:
	tox -e docs-latex

pre-commit:
	pre-commit run --all-files

build:
	tox -e clean
	tox -e build

tpublish: build version
	tox -e publish

publish: build version
	tox -e publish -- --repository pypi

version:
	python -m setuptools_scm

.PHONY: all test install lint format build pre-commit docs test-all docs-latex publish tpublish tag-version
