---
on:
  issues:
    types: [opened,reopened]
engine: gemini
permissions:
  contents: read
  issues: read
  pull-requests: read
safe-outputs:
  add-comment:
  add-labels:
---
# Autonomous Issue Triage

Read issue #${{ github.event.issue.number }}. 

## 1. Classification & Labeling
Analyze the issue text to categorize it. Use the `add-labels` safe output:
- Apply `bug` if it reports incorrect behavior or crashes.
- Apply `enhancement` if it requests new functionality.
- Apply `question` if it asks for help or clarification.

## 2. Completeness Gate
- **If Bug:** Check if the author provided reproduction steps, expected behavior, and a version number. 
- **If Feature:** Check if a concrete use case is provided.
- **Action:** If crucial details are missing, use the `add-comment` safe output to immediately request the specific missing information. Do not proceed to root cause analysis until the issue is actionable.

## 3. Root Cause / Architecture Analysis
If the issue is actionable, search the repository context. Identify the most likely subsystems or files in the codebase that are relevant to the issue. Use the `add-comment` safe output to post a brief technical summary of where maintainers should look first to address the ticket.

## 4. STOP EXECUTION
**CRITICAL:** Your job is ONLY to triage the issue. You are strictly forbidden from writing code, modifying files, or attempting to install dependencies to fix the issue yourself. Once you have posted the comment via the `add-comment` safe output, you MUST call the `noop` tool with a message explaining you have completed the triage, and then immediately terminate.