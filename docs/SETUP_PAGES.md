# Enabling GitHub Pages for Pitwall Agent

This guide explains how to publish the landing page in `docs/` to GitHub Pages.

---

## ⚡ Fastest route (recommended — 20 seconds, no workflow file needed)

The landing page at `docs/index.html` is a **single self-contained HTML file**
with no build step, so Pages can serve it straight from the branch:

1. Open **<https://github.com/Dabi-init/endurance-stint-planner/settings/pages>**
   (you must be signed in as the repository owner).
2. Under **Build and deployment → Source**, choose **Deploy from a branch**.
3. Set **Branch** to `main` and the folder to **`/docs`**.
4. Click **Save**.

Within about a minute the site is live at:

<https://dabi-init.github.io/endurance-stint-planner/>

That is all that is required. No workflow file, no Actions permission, no build.

### Until Pages is enabled

The same page can be viewed right now, with no setup, through GitHub's raw HTML
renderer:

<https://htmlpreview.github.io/?https://github.com/Dabi-init/endurance-stint-planner/blob/main/docs/index.html>

### After Pages is enabled

Set the repository homepage so the link appears on the repo sidebar:
**Code tab → About (gear icon) → Website →**
`https://dabi-init.github.io/endurance-stint-planner/`

While you are there, add these **Topics** for discoverability:
`endurance-racing`, `race-strategy`, `sim-racing`, `fuel-calculator`,
`stint-planner`, `pit-stop-strategy`, `tyre-strategy`, `local-first`, `cli`,
`python`

---

## Alternative: GitHub Actions source

Use this only if you later add a build step to the site. It requires the
deployment workflow at `.github/workflows/pages.yml`.

## 1. Enable Pages with the GitHub Actions source

1. Open the repository on GitHub: `https://github.com/Dabi-init/endurance-stint-planner`
2. Click **Settings** (top navigation bar of the repository).
3. In the left sidebar, click **Pages**.
4. Under **Build and deployment → Source**, select **GitHub Actions**
   (do *not* select "Deploy from a branch").
5. The page saves automatically. You should now see a note that Pages will be
   built by your workflows.

## 2. Confirm the workflow file is present on `main`

1. Go to the **Code** tab and confirm `.github/workflows/pages.yml` exists on the
   `main` branch.
2. If it is missing (for example, if a push was rejected because the token lacked
   the `workflow` scope), create it manually:
   - Click **Add file → Create new file**.
   - Name it `.github/workflows/pages.yml`.
   - Paste the YAML from
     [`.github/pages-workflow.yml.example`](../.github/pages-workflow.yml.example)
     (or from the "Workflow content" section below).
   - Commit directly to `main` (or via a pull request).

## 3. Run the first deployment

1. Go to the **Actions** tab.
2. Select **Deploy GitHub Pages** in the left sidebar.
3. Click **Run workflow → Run workflow** (this uses the `workflow_dispatch`
   trigger, so you do not have to wait for a `docs/` change).
4. Wait for the `deploy` job to finish. It should show a green check.

## 4. Verify the site

1. Return to **Settings → Pages**. The published URL appears at the top:
   `https://dabi-init.github.io/endurance-stint-planner/`
2. Open the URL and confirm the landing page renders.
3. Check that `robots.txt` and `sitemap.xml` are reachable:
   - `https://dabi-init.github.io/endurance-stint-planner/robots.txt`
   - `https://dabi-init.github.io/endurance-stint-planner/sitemap.xml`

## 5. Optional: set the repository social preview image

1. **Settings → General → Social preview → Edit → Upload an image**.
2. Upload `docs/social-preview.png` (1280×640 px).
   See [`social-preview-instructions.md`](social-preview-instructions.md).

---

## Workflow content

```yaml
name: Deploy GitHub Pages
on:
  push:
    branches: [main]
    paths: ['docs/**']
  workflow_dispatch:
permissions:
  contents: read
  pages: write
  id-token: write
concurrency:
  group: pages
  cancel-in-progress: false
jobs:
  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v4
      - uses: actions/upload-pages-artifact@v3
        with:
          path: docs/
      - id: deployment
        uses: actions/deploy-pages@v4
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `refusing to allow ... to create or update workflow ... without 'workflow' scope` on push | The pushing token lacks the `workflow` scope | Create the file through the GitHub web UI (step 2) or push with a PAT that has `workflow` scope |
| Workflow fails at "Configure Pages" | Pages source is not set to GitHub Actions | Repeat step 1 |
| `HttpError: Resource not accessible by integration` | Missing `pages: write` / `id-token: write` permissions | Confirm the `permissions:` block matches the YAML above |
| Site returns 404 after a green run | Propagation delay, or `docs/index.html` missing | Wait a minute and hard-refresh; confirm `docs/index.html` exists |
| Deployment blocked on environment approval | `github-pages` environment has protection rules | **Settings → Environments → github-pages** and relax the rules |
