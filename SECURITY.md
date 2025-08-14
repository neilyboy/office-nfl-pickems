# Security Policy

## Supported Versions

This project is maintained on a best-effort basis. Reported vulnerabilities for the latest tagged release will be reviewed.

## Reporting a Vulnerability

Please use GitHub's private vulnerability reporting if enabled for this repository. If it is not available, open a new issue with the `security` label and minimal details, and a maintainer will reach out for private follow-up.

Do not publicly disclose vulnerabilities before we have had a chance to investigate and publish a fix.

## Secrets

- Never commit secrets to the repository
- Use environment variables (`.env`) for configuration
- Rotate secrets when compromised or shared beyond trusted parties
