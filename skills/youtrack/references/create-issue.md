# Create an issue safely

Use this workflow when the user asks to create a ticket, task, bug, story, or issue.

## 1. Resolve the target

Determine the YouTrack server and project from explicit user wording or trusted local configuration. If either is ambiguous, ask the user. Never guess a write target.

Load any organization-specific issue rules from the user's local instructions. Such rules stay outside this public skill and override the generic defaults below.

## 2. Discover live values

Before drafting the issue:

1. Run `projects --query ...` to verify the project.
2. Run `users --query ...` if an assignee was requested.
3. Run `fields --project KEY` to discover required fields and valid enum/user values.

Do not hardcode internal field or user IDs. Use selector-based `--custom-fields` where practical.

Generic defaults, only when local rules and the user do not say otherwise:

- type: `Task` if that value exists;
- priority: `Normal` if that value exists;
- state: leave at the project default;
- language: match the user's request unless local rules require another language.

## 3. Show an approval-ready draft

Show the exact:

- server and project;
- summary;
- complete description;
- assignee, type, priority, and other significant fields;
- attachment names, if any.

Ask for explicit approval. The initial request to create a ticket is not approval of the final draft. Any target, text, or field change invalidates the previous approval.

## 4. Create after approval

Enable both write gates only for the approved operation:

```bash
YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write create \
  --project DEMO \
  --summary "Approved summary" \
  --description @body.md \
  --custom-fields @fields.json
```

Use a temporary UTF-8 file for multiline descriptions. Delete temporary files after the command completes.

If attachments are required, show the created issue ID and exact file list, then request a separate confirmation before `attach`. Re-uploading may create duplicates.

## 5. Report

Return the readable issue ID, URL, project, and assignee. Do not expose tokens, environment values, or unrelated lookup output.
