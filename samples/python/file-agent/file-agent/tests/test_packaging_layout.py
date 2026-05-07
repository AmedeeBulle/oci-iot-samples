#
# Tests for Python package layout.
#
# Copyright (c) 2026 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at
# https://oss.oracle.com/licenses/upl.
#
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS HEADER.
#

import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent


def test_python_project_metadata_lives_under_app_directory():
    assert not (REPO_ROOT / "pyproject.toml").exists()
    assert (PROJECT_ROOT / "pyproject.toml").is_file()


def test_package_source_lives_under_app_directory():
    assert not (REPO_ROOT / "file_agent").exists()
    assert (PROJECT_ROOT / "file_agent").is_dir()


def test_setuptools_discovers_only_file_agent_package_directory():
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)

    package_find = pyproject["tool"]["setuptools"]["packages"]["find"]

    assert package_find["where"] == ["."]
    assert package_find["include"] == ["file_agent*"]
