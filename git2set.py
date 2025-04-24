import argparse
import subprocess
import json
import os
# import tempfile # No longer needed
# import shutil # No longer needed
import pathlib
import sys

# Define the separator used in git log format
GIT_LOG_SEPARATOR = "\x1f"

def run_git_command(command, cwd, check=True, capture_output=True, text=True):
    """Helper function to run a Git command."""
    try:
        # print(f"Running command: {' '.join(command)} in {cwd}", file=sys.stderr) # Debugging
        result = subprocess.run(command, cwd=cwd, check=check, capture_output=capture_output, text=text, encoding='utf-8', errors='ignore')
        # print(f"Command stdout:\n{result.stdout[:200]}...", file=sys.stderr) # Debugging
        # print(f"Command stderr:\n{result.stderr[:200]}...", file=sys.stderr) # Debugging
        return result
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(command)}", file=sys.stderr)
        print(f"Return code: {e.returncode}", file=sys.stderr)
        print(f"Stderr: {e.stderr}", file=sys.stderr)
        print(f"Stdout: {e.stdout}", file=sys.stderr)
        raise  # Re-raise the exception to be handled by the caller
    except FileNotFoundError:
        print(f"Error: 'git' command not found. Is Git installed and in your PATH?", file=sys.stderr)
        raise

def get_commit_diff(commit_hash, file_path, repo_path):
    """Gets the diff for a specific file in a specific commit."""
    # Try getting diff against parent first
    try:
        # Use --no-patch to check existence and type, then get diff if it's not a submodule etc.
        # This might be overly complex, stick to simpler diff first.
        diff_command = ['git', 'diff', f'{commit_hash}^..{commit_hash}', '--', file_path]
        result = run_git_command(diff_command, cwd=repo_path)
        return result.stdout
    except subprocess.CalledProcessError as e:
        # This often fails for the very first commit (no parent ^) or merge commits (handled by --no-merges).
        # Fallback to 'git show' which includes headers but works more reliably for single commits.
        # print(f"Warning: 'git diff {commit_hash}^..{commit_hash}' failed for {file_path}. Falling back to 'git show'. Error: {e.stderr}", file=sys.stderr)
        try:
            show_command = ['git', 'show', commit_hash, '--', file_path]
            result = run_git_command(show_command, cwd=repo_path)
            # Attempt to strip the header git show adds
            diff_content = result.stdout
            diff_start_index = diff_content.find('\ndiff --git')
            if diff_start_index != -1:
                 # Find the start of the actual diff content after the header
                 header_end_index = diff_content.find('\n--- a/', diff_start_index)
                 if header_end_index != -1:
                     return diff_content[header_end_index+1:] # +1 to remove leading newline
            # If header stripping fails, return the full 'show' output as a best effort
            return diff_content
        except subprocess.CalledProcessError as show_e:
            print(f"Error: Both 'git diff' and 'git show' failed for file '{file_path}' in commit '{commit_hash}'.", file=sys.stderr)
            print(f"Show command error: {show_e.stderr}", file=sys.stderr)
            return None # Indicate failure

def main():
    parser = argparse.ArgumentParser(description="Generate AI training dataset from Git repository history.")
    parser.add_argument('--system-prompt', required=True, help='System prompt for the dataset messages.')
    parser.add_argument('--repo', required=True, help='SSH URL or path of the Git repository.')
    parser.add_argument('--mask', required=True, help='Glob pattern for files to include (relative to repo root).')
    parser.add_argument('--output', required=True, help='Path for the output JSONL file.')
    parser.add_argument('--depth', help='Timespan to limit history (e.g., "1 year", "6 months", compatible with `git log --since`).')
    parser.add_argument('--cache-dir', default=os.path.join(os.getcwd(), '.git_cache'), help='Directory to cache cloned repositories (default: ./.git_cache)')

    args = parser.parse_args()

    print(f"Starting dataset generation for repo: {args.repo}", file=sys.stderr)
    print(f"Using cache directory: {args.cache_dir}", file=sys.stderr)

    output_count = 0
    error_count = 0

    try:
        # --- Start Cache Logic ---
        # Derive repo name from URL/path for cache subdirectory
        repo_identifier = args.repo.split('/')[-1] # Get last part
        repo_name = repo_identifier.replace('.git', '') # Remove .git suffix if present
        if not repo_name: # Handle potential edge cases like invalid URLs or paths ending in /
             repo_identifier = args.repo.rstrip('/').split('/')[-1] # Try removing trailing slash
             repo_name = repo_identifier.replace('.git', '')
             if not repo_name:
                 print(f"Error: Could not determine repository name from source: {args.repo}", file=sys.stderr)
                 sys.exit(1)

        # Use the provided or default cache directory
        repo_path = os.path.join(args.cache_dir, repo_name)

        os.makedirs(args.cache_dir, exist_ok=True) # Ensure cache base directory exists

        if os.path.isdir(os.path.join(repo_path, '.git')):
            print(f"Found existing repository cache at: {repo_path}", file=sys.stderr)
            print("Fetching latest changes...", file=sys.stderr)
            try:
                # Fetch all remote branches and tags, remove stale remote branches
                # Use --quiet to reduce noise
                run_git_command(['git', 'fetch', 'origin', '--prune', '--quiet'], cwd=repo_path)
                # Optional: Clean the working directory just in case (might not be needed)
                # run_git_command(['git', 'checkout', '.'], cwd=repo_path)
                print("Fetch complete.", file=sys.stderr)
            except subprocess.CalledProcessError as e:
                # If fetch fails (e.g., offline, bad permissions), warn but proceed with cached version
                print(f"Warning: Failed to fetch updates for repository {repo_path}. Using cached version. Error: {e.stderr}", file=sys.stderr)
            except FileNotFoundError:
                 # Error already printed by run_git_command
                 sys.exit(1)
        else:
            print(f"Cloning repository into cache directory: {repo_path}", file=sys.stderr)
            try:
                # Clone without checking out files initially, use quiet
                run_git_command(['git', 'clone', '--no-checkout', '--quiet', args.repo, repo_path], cwd=args.cache_dir) # Clone into cache_dir base
                # Checkout default branch (or ensure repo is usable), use quiet
                run_git_command(['git', 'checkout', '--quiet'], cwd=repo_path) # Checkout inside the repo_path
                print("Clone complete.", file=sys.stderr)
            except subprocess.CalledProcessError:
                print(f"Error: Failed to clone repository {args.repo}. Check URL/path and access rights.", file=sys.stderr)
                sys.exit(1)
            except FileNotFoundError:
                 # Error already printed by run_git_command
                 sys.exit(1)
        # --- End Cache Logic ---

        # --- The rest of the script continues below, using the determined repo_path ---

        print("Fetching commit history from all branches (excluding merges)...", file=sys.stderr)
        # Add --all to get history from all branches
        # Add --no-merges to exclude merge commits
        log_command = ['git', 'log', '--all', '--no-merges', f'--pretty=format:%H{GIT_LOG_SEPARATOR}%s']
        if args.depth:
            log_command.append(f'--since={args.depth}')

        try:
            log_result = run_git_command(log_command, cwd=repo_path)
        except subprocess.CalledProcessError:
            print(f"Error: Failed to get git log from {repo_path}.", file=sys.stderr)
            sys.exit(1)

        commits = log_result.stdout.strip().split('\n')
        total_commits = len(commits)
        print(f"Found {total_commits} commits to process.", file=sys.stderr)

        # Ensure the output directory exists
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(args.output, 'w', encoding='utf-8') as outfile:
            for i, commit_line in enumerate(commits):
                if not commit_line: continue # Skip empty lines if any

                try:
                    commit_hash, commit_message = commit_line.split(GIT_LOG_SEPARATOR, 1)
                except ValueError:
                    print(f"Warning: Skipping malformed commit line: {commit_line}", file=sys.stderr)
                    continue

                # print(f"Processing commit {i+1}/{total_commits}: {commit_hash[:7]} - {commit_message[:50]}...", file=sys.stderr) # Reduce verbosity

                try:
                    # Get files changed in this commit
                    diff_tree_command = ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash]
                    changed_files_result = run_git_command(diff_tree_command, cwd=repo_path)
                    changed_files = changed_files_result.stdout.strip().split('\n')
                except subprocess.CalledProcessError:
                    print(f"Warning: Failed to get changed files for commit {commit_hash}. Skipping.", file=sys.stderr)
                    error_count += 1
                    continue

                if not changed_files or (len(changed_files) == 1 and not changed_files[0]):
                    # print(f"No files changed in commit {commit_hash[:7]}?", file=sys.stderr) # Debugging
                    continue # Skip commits with no file changes listed

                # Filter files by mask
                repo_path_obj = pathlib.Path(repo_path) # Base path for potential existence checks
                mask_pattern = args.mask
                # Adjust mask if it starts with './' as Path.match doesn't like it
                if mask_pattern.startswith('./'):
                    mask_pattern = mask_pattern[2:]

                matching_files = []
                for file_path_str in changed_files:
                    if not file_path_str: continue # Skip empty lines
                    # Create a Path object relative to the repo root for matching
                    # Note: git outputs paths relative to repo root
                    try:
                        # Use pathlib's match for globbing
                        if pathlib.Path(file_path_str).match(mask_pattern):
                             matching_files.append(file_path_str)
                    except OSError as path_e:
                         # Handle potential errors with invalid filenames from git history
                         print(f"Warning: Skipping potentially invalid file path '{file_path_str}' from commit {commit_hash[:7]}: {path_e}", file=sys.stderr)
                         continue


                # print(f"Commit {commit_hash[:7]}: Found {len(matching_files)} matching files.", file=sys.stderr) # Debugging

                if len(matching_files) > 0: # Skip if no files matched the mask for this commit
                    # Process matching files for this commit
                    for file_path in matching_files:
                        # print(f"  Processing file: {file_path}", file=sys.stderr) # Reduce verbosity
                        file_diff = get_commit_diff(commit_hash, file_path, repo_path)

                        if file_diff is not None and file_diff.strip(): # Ensure diff is not empty
                            # Format and write to JSONL
                            data = {
                                "messages": [
                                    {"role": "system", "content": args.system_prompt},
                                    {"role": "user", "content": commit_message.strip()},
                                    {"role": "assistant", "content": file_diff.strip()}
                                ]
                            }
                            try:
                                json.dump(data, outfile, ensure_ascii=False)
                                outfile.write('\n')
                                output_count += 1
                            except Exception as e:
                                print(f"Error writing JSON for commit {commit_hash}, file {file_path}: {e}", file=sys.stderr)
                                error_count += 1
                        elif file_diff is None:
                            # Error occurred getting diff
                            error_count += 1
                            print(f"Skipping file '{file_path}' in commit '{commit_hash}' due to diff retrieval error.", file=sys.stderr)
                        # else: diff was empty, just skip

                # Progress indicator every 100 commits processed
                if (i + 1) % 100 == 0:
                     print(f"Processed {i+1}/{total_commits} commits...", file=sys.stderr)


    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

    print(f"\nDataset generation complete.", file=sys.stderr)
    print(f"Output saved to: {args.output}", file=sys.stderr)
    print(f"Total entries generated: {output_count}", file=sys.stderr)
    if error_count > 0:
        print(f"Warnings/Errors encountered: {error_count}", file=sys.stderr)

if __name__ == "__main__":
    main()
