# Git2Set: AI Dataset Generator from Git History

Git2Set is a Python script that clones a Git repository and processes its commit history to generate a JSONL dataset suitable for training AI models. Each line in the output file represents a modification to a specific file within a commit. The dataset uses the commit message as the "user" prompt and the file's diff as the "assistant's" response, paired with a configurable system prompt.

## Features

*   Clones repositories via SSH URLs.
*   Filters files based on a glob pattern (`--mask`).
*   Optionally limits the commit history processed based on a timespan (`--depth`).
*   Generates output in JSONL format, ready for fine-tuning.
*   Allows customization of the system prompt used in the dataset.

## Requirements

*   Python 3.x
*   Git command-line tool installed and configured (especially for SSH key access to private repositories).

## Usage

```bash
python git2set.py \
  --system-prompt "You are a helpful coding assistant. Analyze the following code change and explain it." \
  --repo "git@github.com:your-username/your-repo.git" \
  --mask "./src/**/*.py" \
  --output "my_dataset.jsonl" \
  --depth "6 months" 
```

## Parameters

*   `--system-prompt` (Required): The text to use for the "system" role in each JSONL entry.
*   `--repo` (Required): The SSH URL of the Git repository to clone (e.g., `git@github.com:user/repo.git`).
*   `--mask` (Required): A glob pattern to filter files within the repository (e.g., `./**/*.js`, `src/components/*.jsx`). The pattern is matched against file paths relative to the repository root.
*   `--output` (Required): The path to the output JSONL file where the dataset will be saved.
*   `--depth` (Optional): A timespan string compatible with `git log --since` to limit the history processed (e.g., "1 year", "3 months", "2 weeks ago"). If omitted, the entire history is processed.

## Output Format

The script generates a JSONL file where each line is a JSON object representing a single file change within a commit:

```json
{"messages": [{"role": "system", "content": "Your provided system prompt."}, {"role": "user", "content": "Commit message text."}, {"role": "assistant", "content": "--- a/path/to/file.ext\n+++ b/path/to/file.ext\n@@ -1,1 +1,1 @@\n-old content\n+new content\n"}]}
{"messages": [{"role": "system", "content": "Your provided system prompt."}, {"role": "user", "content": "Another commit message."}, {"role": "assistant", "content": "--- a/another/file.py\n+++ b/another/file.py\n@@ -10,3 +10,4 @@\n class MyClass:\n     pass\n+    # Added a comment\n"}]}
```

## Error Handling

The script includes basic error handling for:
*   Invalid or inaccessible repository URLs (Git clone failures).
*   Issues running Git commands.
*   File system errors during output writing.

Ensure your Git installation is working and your SSH keys are configured correctly before running the script.
