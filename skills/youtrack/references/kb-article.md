# Publish a Knowledge Base article safely

Use this workflow when the user asks to create, publish, update, or attach files to a YouTrack Knowledge Base article.

## 1. Resolve placement and avoid duplicates

Determine the YouTrack server and project from explicit user wording or trusted local configuration. Ask if ambiguous.

Search existing articles:

```bash
uv run --python 3.13 python scripts/yt.py articles --query "project: DEMO" --top 100
```

Use the result to detect duplicates and select a parent. `--parent` requires the parent's internal `id`, not `idReadable`.

## 2. Prepare content

Write non-trivial content to a temporary UTF-8 Markdown file and pass it as `--content @file.md`.

- Do not start the body with an H1 that duplicates the article summary.
- Preserve code blocks, tables, and diagrams.
- Reference inline attachment images by their file names.
- Follow any organization-specific writing rules from trusted local instructions.

## 3. Preview and create

Show the exact server, project, summary, parent, and complete content. Ask for explicit approval. Any change requires a new preview and approval.

```bash
YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write article-create \
  --project DEMO \
  --summary "Approved title" \
  --content @article.md \
  --parent INTERNAL_ID
```

Omit `--parent` for a top-level article.

## 4. Attach files separately

After creation, show the article ID and exact file list. Ask for a separate confirmation before upload:

```bash
YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write article-attach \
  DEMO-A-1 image-1.png image-2.png
```

Verify with `article-attachments DEMO-A-1`. A same-named upload may create a duplicate attachment.

## 5. Update or link separately

An article update and an issue comment linking to the article are separate writes. Show the exact target and content and obtain separate approval for each operation.

## 6. Report

Return the readable article ID, URL, project, parent, and attachment status. Never expose the token or unrelated article content.
