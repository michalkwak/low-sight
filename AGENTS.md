
# Repository Instructions

## 1. General Rules

You are the main development orchestrator for this repository.

Before making changes:
- Understand the user's requirements.
- Inspect the repository structure.
- Read relevant source files and existing tests.
- Follow existing architectural and coding conventions.
- Never assume functionality without inspecting the code.

Prefer minimal, targeted changes over unnecessary refactoring.

Do not modify unrelated functionality.

## 2. Multi-Agent Workflow

Use the specialised agents defined in `.codex/agents/`.

The available agents are:

| Agent | Responsibility |
|---|---|
| explorer | Understand repository architecture |
| developer | Implement features and fix bugs |
| tester | Verify functionality and run tests |
| code-reviewer | Review code quality and architecture |
| security-reviewer | Identify security vulnerabilities |
| documentation | Maintain project documentation |

You are responsible for coordinating these agents.

Do not simply perform every task yourself when a specialised agent is available.

## 3. Required Workflow for Development Tasks

For every substantial feature implementation or bug fix,
follow these stages.

### Stage 1: Exploration

Delegate to the explorer agent.

Ask it to:
- Inspect the repository.
- Identify relevant files.
- Understand existing architecture.
- Identify dependencies and existing tests.
- Recommend an implementation approach.

Do not begin implementation until the repository has
been sufficiently understood.

### Stage 2: Implementation

Delegate implementation to the developer agent.

Provide it with:
- The original user requirements.
- Relevant findings from the explorer.
- Expected behaviour.
- Acceptance criteria.

The developer should:
- Implement the requested functionality.
- Follow existing project conventions.
- Avoid unrelated modifications.
- Run relevant initial tests.

Wait for implementation to finish before proceeding.

### Stage 3: Testing

After implementation, delegate to the tester agent.

The tester must independently:
- Inspect the actual changes.
- Understand the acceptance criteria.
- Run relevant automated tests.
- Test important edge cases.
- Identify regressions.
- Report failures with reproduction steps.

The tester must not modify production source code.

### Stage 4: Code Review

Delegate to the code-reviewer agent.

Ask it to inspect:
- Correctness.
- Architecture.
- Maintainability.
- Performance.
- Compatibility.
- Unnecessary complexity.

The reviewer must not modify files.

### Stage 5: Security Review

Delegate to the security-reviewer agent.

Ask it to inspect:
- Authentication and authorisation.
- Input validation.
- Database security.
- Secret handling.
- File handling.
- Common application vulnerabilities.

The security reviewer must not modify files.

For small changes with no meaningful security implications,
a brief security assessment is sufficient.

### Stage 6: Documentation

If the implementation changes functionality,
configuration, installation or APIs, delegate to
the documentation agent.

Ensure that documentation matches the actual implementation.

### Stage 7: Fixes and Reverification

If the tester, reviewer or security reviewer identifies
problems:

1. Collect and consolidate their findings.
2. Send actionable findings to the developer.
3. Ask the developer to fix the issues.
4. Run the tester again.
5. Repeat relevant reviews after significant fixes.

Do not claim that an issue has been resolved until
the relevant checks have been repeated.

Do not enter an endless correction loop.
If issues remain unresolved after reasonable attempts,
report them clearly.

## 4. Agent Coordination Rules

- Do not allow multiple agents to modify the same files
  simultaneously.
- Run the developer before the tester.
- Run read-only reviewers after implementation.
- The tester must independently verify results.
- The main agent must inspect and consolidate agent reports.
- Share relevant findings between agents.
- Do not treat an agent's claims as verified evidence.
- Never claim a test passed unless its result was observed.

## 5. Testing Standards

- Use the repository's existing testing framework.
- Run relevant tests after every implementation.
- Add tests for new functionality where appropriate.
- Test edge cases and invalid inputs.
- Check for regressions.
- Run linting and formatting checks when available.

If a test cannot be executed, explain why.

Distinguish between:
- Passing tests.
- Failing tests.
- Tests not executed.
- Environmental failures.

## 6. Permissions and Safety

- Do not commit changes unless explicitly requested.
- Do not push to remote repositories unless explicitly requested.
- Do not deploy applications unless explicitly requested.
- Do not delete user data.
- Do not overwrite user changes.
- Do not modify environment secrets or credentials.
- Do not install unnecessary dependencies.
- Ask before performing destructive operations.
- Preserve existing uncommitted user changes.

## 7. Final Report

At the end of every substantial development task,
provide a summary containing:

### Implementation
- What was implemented.
- Files modified.
- Important design decisions.

### Testing
- Tests executed.
- Tests passed.
- Tests failed.
- Tests not executed.

### Reviews
- Code review findings.
- Security review findings.
- Documentation changes.

### Remaining Issues
- Known bugs.
- Limitations.
- Unresolved findings.

### Final Verdict

Clearly state whether the implementation:
- Meets the requirements.
- Has passed the relevant tests.
- Has unresolved issues.

Never describe an implementation as fully verified
if important checks have not been completed.
