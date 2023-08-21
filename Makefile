SHELL := /bin/bash
PROJECT := tagpack-tool
VENV := .venv
RELEASE := 'v23.06'
RELEASESEM := 'v1.6.0'

include .env

all: format lint test build

tag-version:
	git diff --exit-code && git diff --staged --exit-code && git tag -a $(RELEASESEM) -m 'Release $(RELEASE)' || (echo "Repo is dirty please commit first" && exit 1)
	git diff --exit-code && git diff --staged --exit-code && git tag -a $(RELEASE) -m 'Release $(RELEASE)' || (echo "Repo is dirty please commit first" && exit 1)

run:
	gs_tagpack_tool_db_url='postgresql://${POSTGRES_USER_TAGSTORE}:${POSTGRES_PASSWORD_TAGSTORE}@localhost:5432/tagstore' uvicorn src.tagpack.web:app

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

.PHONY: all test install lint format build pre-commit docs test-all docs-latex publish tpublish tag-version postgres-reapply-config run
