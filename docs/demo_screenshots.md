# Demo Screenshots Guide

Add screenshots for each key product step so reviewers can scan the workflow quickly.

## Required images

Save these images in `docs/screenshots/` using the exact filenames:

1. `01_upload_step.png` — upload area with selected files
2. `02_pre_run_validation.png` — pre-run validation checks
3. `03_draft_summary.png` — draft totals section
4. `04_parsed_slips_tab.png` — parsed slips tab
5. `05_approval_gate.png` — approval checkboxes and decision section
6. `06_approved_state.png` — success state after approval

## Capture commands (macOS)

Use built-in capture:

```bash
screencapture -i docs/screenshots/01_upload_step.png
```

Repeat for each filename above.

## README integration snippet

After screenshots are captured, add this section to README:

```markdown
## Demo screenshots

![Upload step](docs/screenshots/01_upload_step.png)
![Pre-run validation](docs/screenshots/02_pre_run_validation.png)
![Draft summary](docs/screenshots/03_draft_summary.png)
![Parsed slips tab](docs/screenshots/04_parsed_slips_tab.png)
![Approval gate](docs/screenshots/05_approval_gate.png)
![Approved state](docs/screenshots/06_approved_state.png)
```
