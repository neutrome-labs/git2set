# Git2Set User Flows

This document outlines common scenarios for using the `git2set.py` script.

## Scenario 1: Basic Dataset Generation

*   **Goal:** Generate a dataset from all Python files (`.py`) in a project's entire history.
*   **User Command:**
    ```bash
    python git2set.py \
      --system-prompt "Analyze the Python code change." \
      --repo "git@github.com:user/project.git" \
      --mask "./**/*.py" \
      --output "project_py_full.jsonl"
    ```
*   **Expected Outcome:** The script clones the repository, processes all commits, and creates `project_py_full.jsonl`. This file contains one JSON line for every instance a `.py` file was modified in any commit throughout the project's history.

## Scenario 2: Time-Limited Generation for Specific Directory

*   **Goal:** Generate a dataset from XML files within the `config` directory, but only considering changes made in the last 3 months.
*   **User Command:**
    ```bash
    python git2set.py \
      --system-prompt "Explain the configuration change." \
      --repo "git@github.com:user/webapp.git" \
      --mask "./config/**/*.xml" \
      --output "webapp_config_recent.jsonl" \
      --depth "3 months"
    ```
*   **Expected Outcome:** The script clones the repository, processes commits only from the last 3 months, and creates `webapp_config_recent.jsonl`. This file contains entries only for modifications to `.xml` files under the `./config/` directory within that timeframe.

## Scenario 3: Invalid or Inaccessible Repository

*   **Goal:** User attempts to run the script with an incorrect or inaccessible SSH repository URL.
*   **User Command:**
    ```bash
    python git2set.py \
      --system-prompt "..." \
      --repo "git@githib.com:user/typo-repo.git" \
      --mask "./**/*.*" \
      --output "error_run.jsonl" 
    ```
*   **Expected Outcome:** The `git clone` command fails. The script catches the error and prints an informative message to the console (stderr) indicating that cloning failed, possibly including the Git error output. The script exits with a non-zero status code, and `error_run.jsonl` is likely not created or is empty.

## Scenario 4: No Matching Files or Commits

*   **Goal:** User runs the script with a mask or depth criteria that doesn't match any file changes in the repository's history (or the specified timespan).
*   **User Command:**
    ```bash
    python git2set.py \
      --system-prompt "Analyze changes." \
      --repo "git@github.com:user/project.git" \
      --mask "./nonexistent_folder/**/*.ext" \
      --output "no_matches.jsonl"
    ```
*   **Expected Outcome:** The script clones the repository and processes the commits. However, no file modifications match the `--mask` (or the time window specified by `--depth`). The script finishes successfully (exit code 0), potentially prints a message like "No matching file changes found for the given criteria.", and creates an empty `no_matches.jsonl` file.
