# Makefile for the pymacos Python package

# Variables
# The import name (the PyPI distribution is "pymacos").
PACKAGE_NAME = macos
PYTHON = python3
PIP = $(PYTHON) -m pip
VENV_DIR = .venv
TEST_DIR = tests
DIST_DIR = dist
DOCS_DIR = docs
DOCS_BUILD_DIR = $(DOCS_DIR)/_build/html

# Colors for output
GREEN = \033[0;32m
YELLOW = \033[0;33m
NC = \033[0m # No Color

# Default target
.PHONY: help
help:
	@echo "$(GREEN)pymacos Python package Makefile$(NC)"
	@echo ""
	@echo "Setup:"
	@echo "  $(YELLOW)venv$(NC)             - Create a virtual environment in $(VENV_DIR)"
	@echo "  $(YELLOW)install$(NC)          - Install the package in development mode"
	@echo "  $(YELLOW)install-dev$(NC)      - Install the package with development dependencies"
	@echo "  $(YELLOW)install-docs$(NC)     - Install the dependencies to build the documentation"
	@echo ""
	@echo "Checks:"
	@echo "  $(YELLOW)test$(NC)             - Run the unit and live tests, but not the intrusive ones: nothing on this Mac changes for good"
	@echo "  $(YELLOW)test-all$(NC)         - Run every test, the intrusive ones too: camera, microphone, browser, launch agent, settings"
	@echo "  $(YELLOW)test-unit$(NC)        - Run the unit tests only (safe: nothing on this Mac changes)"
	@echo "  $(YELLOW)test-live$(NC)        - Run the live tests only, but not the intrusive ones"
	@echo "  $(YELLOW)test-live-all$(NC)    - Run the live tests only, the intrusive ones too"
	@echo "  $(YELLOW)test-coverage$(NC)    - Run the unit tests with a coverage report, failing under the $(COVERAGE_MIN)% CI gates on for every Python"
	@echo "  $(YELLOW)lint$(NC)             - Run the linter (flake8)"
	@echo "  $(YELLOW)type-check$(NC)       - Run the type checker (mypy)"
	@echo "  $(YELLOW)check$(NC)            - Run lint, type-check and test-unit: what CI runs on a pull request, except the docs and live tests"
	@echo ""
	@echo "Documentation:"
	@echo "  $(YELLOW)docs$(NC)             - Build the HTML documentation (output: $(DOCS_BUILD_DIR))"
	@echo "  $(YELLOW)docs-serve$(NC)       - Live-reload docs server at http://127.0.0.1:8000"
	@echo "  $(YELLOW)docs-clean$(NC)       - Remove the docs build directory"
	@echo ""
	@echo "Packaging:"
	@echo "  $(YELLOW)build$(NC)            - Build the wheel and source distribution"
	@echo "  $(YELLOW)validate$(NC)         - Build and check the distributions with twine"
	@echo "  $(YELLOW)version$(NC)          - Show the current version"
	@echo "  $(YELLOW)clean$(NC)            - Remove build, test and cache artifacts"

# Create virtual environment
.PHONY: venv
venv:
	@echo "$(GREEN)Creating virtual environment...$(NC)"
	$(PYTHON) -m venv $(VENV_DIR)
	@echo "$(YELLOW)To activate: source $(VENV_DIR)/bin/activate$(NC)"

# Install package in development mode (it has no runtime dependencies)
.PHONY: install
install:
	@echo "$(GREEN)Installing package in development mode...$(NC)"
	$(PIP) install -e .

# Install development dependencies (pytest, flake8, mypy, build, twine)
.PHONY: install-dev
install-dev:
	@echo "$(GREEN)Installing development dependencies...$(NC)"
	$(PIP) install -e ".[dev]"

# Install the documentation dependencies, plus the package so autodoc can import it
.PHONY: install-docs
install-docs:
	@echo "$(GREEN)Installing documentation dependencies...$(NC)"
	$(PIP) install -r $(DOCS_DIR)/requirements.txt
	$(PIP) install -e .

# The switches of the intrusive live tests (CONTRIBUTING.md lists what each does to this Mac): off for
# `test` and `test-live`, even when set in this shell, and on for `test-all` and `test-live-all`.
LIVE_SWITCHES = PYMACOS_CAPTURE_TESTS PYMACOS_BROWSER_TESTS PYMACOS_SCHEDULE_TESTS PYMACOS_SETTINGS_TESTS
WITHOUT_SWITCHES = env $(foreach switch,$(LIVE_SWITCHES),-u $(switch))
WITH_SWITCHES = env $(foreach switch,$(LIVE_SWITCHES),$(switch)=1)

# The unit tests and the live ones, but not the intrusive ones: nothing is left
# changed, and after the first run (macOS asks once for the Automation
# permission) nothing waits for an answer. The live tests still use (and
# restore) the clipboard and the volume, show a few dialogs and a test window,
# and steal the focus for a moment: run them when you aren't typing.
.PHONY: test
test:
	@echo "$(GREEN)Running the unit and live tests, but not the intrusive ones...$(NC)"
	$(WITHOUT_SWITCHES) $(PYTHON) -m pytest $(TEST_DIR) -v -rs

# Everything, the intrusive live tests too: the camera and the microphone turn
# on, macOS asks for permissions (answer them: unanswered, a test waits, then
# fails) and announces a launch agent, and settings change before they're put
# back. Run it at the Mac, and let it finish.
.PHONY: test-all
test-all:
	@echo "$(GREEN)Running every test, the intrusive ones too (camera, microphone, browser, schedule, settings)...$(NC)"
	$(WITH_SWITCHES) $(PYTHON) -m pytest $(TEST_DIR) -v -rs

# The unit tests, which don't touch the system (they also run on Linux).
.PHONY: test-unit
test-unit:
	@echo "$(GREEN)Running unit tests...$(NC)"
	$(PYTHON) -m pytest $(TEST_DIR) -v -m "not live"

# The live tests only, as in `test`, and as in `test-all`.
.PHONY: test-live
test-live:
	@echo "$(GREEN)Running live tests, but not the intrusive ones...$(NC)"
	$(WITHOUT_SWITCHES) $(PYTHON) -m pytest $(TEST_DIR)/live -v -rs

.PHONY: test-live-all
test-live-all:
	@echo "$(GREEN)Running live tests, the intrusive ones too (camera, microphone, browser, schedule, settings)...$(NC)"
	$(WITH_SWITCHES) $(PYTHON) -m pytest $(TEST_DIR)/live -v -rs

# The unit tests with coverage, held to the gate CI applies on every Python (it
# gates both suites together on one, where the live tests' coverage is known).
# Keep it in step with --cov-fail-under in .github/workflows/test.yml.
COVERAGE_MIN = 70

.PHONY: test-coverage
test-coverage:
	@echo "$(GREEN)Running unit tests with coverage...$(NC)"
	$(PYTHON) -m pytest $(TEST_DIR) -m "not live" --cov=$(PACKAGE_NAME) --cov-report=html --cov-report=term --cov-fail-under=$(COVERAGE_MIN)
	@echo "$(YELLOW)HTML report available at htmlcov/index.html$(NC)"

# Run linter
.PHONY: lint
lint:
	@echo "$(GREEN)Running linter (flake8)...$(NC)"
	$(PYTHON) -m flake8 $(PACKAGE_NAME) $(TEST_DIR)

# Run type checker (config in pyproject.toml)
.PHONY: type-check
type-check:
	@echo "$(GREEN)Running type checker (mypy)...$(NC)"
	$(PYTHON) -m mypy $(PACKAGE_NAME)

# Everything CI runs on a pull request, except the docs build and the live tests
.PHONY: check
check: lint type-check test-unit
	@echo "$(GREEN)All checks passed!$(NC)"

# Build the HTML documentation with the same flags as CI and Read the Docs:
# warnings, including broken cross-references (-n), fail the build.
.PHONY: docs
docs:
	@echo "$(GREEN)Building HTML documentation...$(NC)"
	$(PYTHON) -m sphinx -n -W --keep-going -b html $(DOCS_DIR) $(DOCS_BUILD_DIR)
	@echo "$(GREEN)Documentation generated at $(DOCS_BUILD_DIR)/index.html$(NC)"

# Live-reload docs server. sphinx-autobuild is installed on demand. After
# changing a toctree, restart it: it only rebuilds changed pages, so the
# sidebar on the other pages goes stale.
.PHONY: docs-serve
docs-serve:
	@echo "$(GREEN)Starting live-reload docs server at http://127.0.0.1:8000$(NC)"
	@$(PYTHON) -c "import sphinx_autobuild" 2>/dev/null || $(PIP) install sphinx-autobuild
	$(PYTHON) -m sphinx_autobuild $(DOCS_DIR) $(DOCS_BUILD_DIR) --open-browser

# Wipe the built docs
.PHONY: docs-clean
docs-clean:
	@echo "$(GREEN)Cleaning docs build directory...$(NC)"
	rm -rf $(DOCS_DIR)/_build

# Build package. Releases are published by the GitHub workflow when a
# release is created, so there is no publish target here.
.PHONY: build
build: clean
	@echo "$(GREEN)Building package...$(NC)"
	$(PYTHON) -m build

# Validate package
.PHONY: validate
validate: build
	@echo "$(GREEN)Validating package...$(NC)"
	$(PYTHON) -m twine check $(DIST_DIR)/*

# Show current version
.PHONY: version
version:
	@$(PYTHON) -c "import $(PACKAGE_NAME); print($(PACKAGE_NAME).__version__)"

# Clean build artifacts
.PHONY: clean
clean:
	@echo "$(GREEN)Cleaning build artifacts...$(NC)"
	rm -rf build $(DIST_DIR) *.egg-info .pytest_cache .mypy_cache htmlcov .coverage coverage.xml
	find . -path ./$(VENV_DIR) -prune -o -type d -name "__pycache__" -exec rm -rf {} +
