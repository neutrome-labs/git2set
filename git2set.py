import argparse
import subprocess
import json
import os
# import tempfile # No longer needed
# import shutil # No longer needed
import pathlib
import sys
import threading
import queue
from concurrent.futures import ThreadPoolExecutor

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

def get_file_content_at_commit(commit_ref, file_path, repo_path):
    """Gets the content of a file at a specific commit revision."""
    if not commit_ref: # Handle cases like initial commit having no parent
        return "" # Return empty string if no commit ref is provided (e.g., parent of first commit)

    command = ['git', 'show', f'{commit_ref}:{file_path}']
    try:
        result = run_git_command(command, cwd=repo_path, check=False) # Don't check=True, handle errors below
        if result.returncode == 0:
            return result.stdout
        else:
            # Common errors: file not found at this revision (new file, deleted file)
            # stderr might contain "fatal: Path '...' does not exist in '...'"
            # print(f"Info: Could not get content for '{file_path}' at ref '{commit_ref}'. It might not exist at this point. Stderr: {result.stderr.strip()}", file=sys.stderr)
            return "" # Return empty string for files not existing at this ref
    except subprocess.CalledProcessError as e:
        # This might indicate a more serious git issue
        print(f"Error running git show for {commit_ref}:{file_path}: {e.stderr}", file=sys.stderr)
        return None # Indicate a failure to retrieve content
    except Exception as e:
        print(f"Unexpected error in get_file_content_at_commit for {commit_ref}:{file_path}: {e}", file=sys.stderr)
        return None # Indicate failure

def process_commit(commit_line, repo_path, mask_pattern, system_prompt):
    """Processes a single commit line to generate dataset entries."""
    if not commit_line:
        return [], 0 # No data, 0 errors

    try:
        commit_hash, commit_message = commit_line.split(GIT_LOG_SEPARATOR, 1)
    except ValueError:
        # print(f"Warning: Skipping malformed commit line: {commit_line}", file=sys.stderr) # Reduce noise
        return [], 1 # No data, 1 error

    commit_data_list = []
    error_count = 0

    try:
        # Get files changed in this commit
        diff_tree_command = ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash]
        # Use check=False and handle potential errors getting file list
        changed_files_result = run_git_command(diff_tree_command, cwd=repo_path, check=False)
        if changed_files_result.returncode != 0:
             print(f"Warning: Failed to get changed files for commit {commit_hash}. Skipping. Stderr: {changed_files_result.stderr.strip()}", file=sys.stderr)
             return [], 1 # No data, 1 error
        changed_files = changed_files_result.stdout.strip().split('\n')

    except subprocess.CalledProcessError: # Should be caught by check=False now, but keep for safety
        print(f"Warning: Failed unexpectedly to get changed files for commit {commit_hash}. Skipping.", file=sys.stderr)
        return [], 1 # No data, 1 error

    if not changed_files or (len(changed_files) == 1 and not changed_files[0]):
        return [], 0 # No data, 0 errors

    matching_files = []
    for file_path_str in changed_files:
        if not file_path_str: continue
        try:
            # Use pathlib's match for globbing
            # Ensure mask_pattern doesn't start with './' for Path.match
            clean_mask = mask_pattern[2:] if mask_pattern.startswith('./') else mask_pattern
            if pathlib.Path(file_path_str).match(clean_mask):
                 matching_files.append(file_path_str)
        except OSError as path_e:
             # Handle potential errors with invalid filenames from git history
             print(f"Warning: Skipping potentially invalid file path '{file_path_str}' from commit {commit_hash[:7]}: {path_e}", file=sys.stderr)
             continue # Skip this invalid file path

    if len(matching_files) > 0:
        for file_path in matching_files:
            parent_ref = f"{commit_hash}^"
            old_content = get_file_content_at_commit(parent_ref, file_path, repo_path)
            new_content = get_file_content_at_commit(commit_hash, file_path, repo_path)

            # Check for errors during content retrieval (returns None on error)
            if old_content is None or new_content is None:
                error_count += 1
                # Error message already printed in get_file_content_at_commit
                # print(f"Skipping file '{file_path}' in commit '{commit_hash}' due to content retrieval error.", file=sys.stderr)
                continue # Skip this file

            # Skip if both old and new content are effectively empty after stripping.
            # We want to capture file deletions (old content exists, new is empty).
            # We also want to capture file creations (old is empty, new exists).
            # Only skip if *both* are empty.
            if not old_content.strip() and not new_content.strip():
                 # print(f"Skipping file '{file_path}' in commit '{commit_hash}' because both old and new content are empty.", file=sys.stderr)
                 continue

            # Format the messages
            old_content_message = f"File: `{file_path}`\n```\n{old_content.strip()}\n```"
            new_content_message = f"File: `{file_path}`\n```\n{new_content.strip()}\n```"

            # Format data for JSONL
            data = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{commit_message.strip()}\n\n{old_content_message}"}, # Combined user message
                    {"role": "assistant", "content": new_content_message}
                ]
            }
            commit_data_list.append(data)

    return commit_data_list, error_count


def main():
    parser = argparse.ArgumentParser(description="Generate AI training dataset from Git repository history.")
    parser.add_argument('--system-prompt', required=True, help='System prompt for the dataset messages.')
    parser.add_argument('--repo', required=True, help='SSH URL or path of the Git repository.')
    parser.add_argument('--mask', required=True, help='Glob pattern for files to include (relative to repo root).')
    parser.add_argument('--output', required=True, help='Path for the output JSONL file.')
    parser.add_argument('--depth', help='Timespan to limit history (e.g., "1 year", "6 months", compatible with `git log --since`).')
    parser.add_argument('--cache-dir', default=os.path.join(os.getcwd(), '.git_cache'), help='Directory to cache cloned repositories (default: ./.git_cache)')
    parser.add_argument('--threads', type=int, default=1, help='Number of worker threads for parallel processing (default: 1 for sequential).')

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

        # Adjust mask if it starts with './' as Path.match doesn't like it
        mask_pattern = args.mask
        if mask_pattern.startswith('./'):
            mask_pattern = mask_pattern[2:]

        print(f"Processing commits using {args.threads} threads...", file=sys.stderr)
        results = []
        futures = []
        processed_count = 0
        total_commits_to_process = len(commits) # Use the actual count

        # Use ThreadPoolExecutor for parallel processing
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            # Submit all commit processing tasks
            for commit_line in commits:
                if not commit_line: continue # Skip empty lines
                future = executor.submit(process_commit, commit_line, repo_path, mask_pattern, args.system_prompt)
                futures.append(future)

            # Process results as they complete
            for future in futures: # Iterate through submitted futures
                try:
                    commit_data_list, commit_errors = future.result() # Get result from completed future
                    if commit_data_list:
                        results.extend(commit_data_list) # Add list of data dicts
                    error_count += commit_errors
                    processed_count += 1

                    # Progress indicator
                    if processed_count % 100 == 0 or processed_count == total_commits_to_process:
                         print(f"Processed {processed_count}/{total_commits_to_process} commits...", file=sys.stderr)

                except Exception as exc:
                    print(f'Commit processing generated an exception: {exc}', file=sys.stderr)
                    error_count += 1 # Count this as an error

        # Write collected results sequentially
        print(f"Writing {len(results)} entries to {args.output}...", file=sys.stderr)
        with open(args.output, 'w', encoding='utf-8') as outfile:
            for data in results:
                 try:
                     json.dump(data, outfile, ensure_ascii=False)
                     outfile.write('\n')
                     output_count += 1
                 except Exception as e:
                     print(f"Error writing JSON data: {e}", file=sys.stderr)
                     # This specific data item might be corrupted, count error but continue
                     error_count += 1


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
