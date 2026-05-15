# Security

## Status of Previous Issues

### CRITICAL — Path Traversal ✅ FIXED
The `/api/search`, `/api/path`, and `/api/path_stream` endpoints no longer accept user-controlled file paths. The database path is now loaded once from the `PLOTTER_DB` environment variable at startup and hardcoded for all requests.

### HIGH — XSS via innerHTML ✅ FIXED  
System names and metadata are now rendered using safe DOM APIs (`textContent`, `createElement`, `createTextNode`) instead of `innerHTML`. This prevents stored XSS attacks from malicious system names in the database.

### MEDIUM — Flask Debug Mode ✅ FIXED
Debug mode is now controlled by the `DEBUG` environment variable (defaults to `false`). The development server no longer exposes the interactive Werkzeug debugger by default.

### MEDIUM — SQL Query with f-string ✅ MITIGATED
The SQL query building in `scripts/distance_cli_sqlite_prefix.py` uses an f-string for placeholder concatenation, but actual parameter values are passed safely via parameterized queries. No SQL injection vector exists in current use.

---

## Known Limitations for Production Deployment

### No Authentication or Authorization
**Risk:** The API endpoints are publicly accessible with no user authentication. Any client can query paths, search systems, and trigger computations.

**Recommendation:** 
- Add authentication (API keys, OAuth, or IP allowlisting) before exposing to untrusted networks.
- Consider Flask-HTTPAuth or similar for lightweight API key validation.
- Use environment variables to gate access (e.g., `PLOTTER_API_KEY`).

### No Rate Limiting
**Risk:** Clients can submit unlimited concurrent pathfinding requests, exhausting server resources (CPU, memory, database connections).

**Recommendation:**
- Implement rate limiting per IP or API key using Flask-Limiter.
- Set reasonable defaults (e.g., 10 requests/minute per client).
- Add request timeouts to prevent long-running searches from blocking threads.

### Insufficient Input Validation
**Risk:** Numeric parameters (`max_hop`, `max_nodes`, `max_neighbors`, `step_threshold`, `expand_factor`) are parsed but not strictly validated for bounds.

**Recommendation:**
- Validate parameter ranges on all endpoints:
  - `max_hop`: positive, reasonable upper bound (e.g., `<= 500000`)
  - `max_nodes`: `>= 1`, `<= 10000`
  - `max_neighbors`: `>= 1`, `<= 2000`
  - `step_threshold`: positive, `<= max_hop`
  - `expand_factor`: `> 1.0`, `<= 10.0`
- Return HTTP 400 with clear error messages for invalid inputs.

### No Request Timeouts
**Risk:** Pathfinding searches on large databases can run indefinitely, blocking worker threads and preventing other requests from being served.

**Recommendation:**
- Set a per-request timeout (e.g., 5–10 minutes via `signal.alarm()` or threading).
- Return HTTP 408 (Request Timeout) to the client with a clear error message.
- Ensure timeout cleanup properly releases database connections.

### Verbose Error Messages
**Risk:** Stack traces and internal error details may leak information about the database schema or implementation.

**Recommendation:**
- Catch exceptions in API handlers and return sanitized messages.
- Log full details server-side for debugging; return generic "Internal error" to clients.
- Example: Instead of `{"error": "table systems not found"}`, return `{"error": "Database query failed"}`.

### No HTTPS/TLS Enforcement
**Risk:** API requests and responses travel in plaintext over HTTP if deployed without HTTPS.

**Recommendation:**
- Always deploy behind HTTPS (use a reverse proxy like Nginx or deploy with production WSGI server).
- Set `Strict-Transport-Security` header to enforce HTTPS.

### Database Permissions
**Risk:** The SQLite database file is stored on disk with default OS permissions. Unauthorized users on the same machine could read or modify it.

**Recommendation:**
- Restrict file permissions to the application user (e.g., `chmod 600 data/systems.db`).
- Use a more robust database (PostgreSQL, etc.) for multi-user environments with per-table ACLs.

### No Logging or Monitoring
**Risk:** Attacks, abuse, and errors are not recorded. Cannot detect anomalies or investigate incidents.

**Recommendation:**
- Enable application logging to capture API requests, errors, and timings.
- Log all search/pathfinding requests with client IP, parameters, and duration.
- Set up alerts for high error rates or unusually long requests.
- Consider using a structured logging library (e.g., Python's `logging` with JSON output).

---

## Supply Chain Security

### Dependency Management

The project currently uses **minimal, well-maintained dependencies**:
- **Flask ecosystem** (web framework, templating, security utilities)
- **Gunicorn** (production WSGI server)
- **Click & Blinker** (CLI and event utilities)

**Current practices:**
- ✅ Exact version pinning in `webapp/requirements.txt`
- ❌ No hash verification or lock files
- ❌ No automated vulnerability scanning
- ❌ No SBOM (Software Bill of Materials)

### Recommended Controls

#### 1. Enable Hash Verification
Add `--require-hashes` to pip installation to ensure packages haven't been tampered with:

```bash
# Generate hashes
pip install pip-tools
pip-compile --generate-hashes webapp/requirements.txt -o webapp/requirements.lock

# Install with hash verification
pip install --require-hashes -r webapp/requirements.lock
```

#### 2. Automated Vulnerability Scanning ✅ DONE
Enable GitHub's **Dependabot** to scan for vulnerable dependencies:
- Create `.github/dependabot.yml`:
  ```yaml
  version: 2
  updates:
    - package-ecosystem: "pip"
      directory: "/webapp"
      schedule:
        interval: "weekly"
      open-pull-requests-limit: 5
      reviewers:
        - cmdr-threethree
  ```
- GitHub will automatically create PRs for security updates.

#### 3. Regular Dependency Audits
Run security audits regularly during development:
```bash
pip install safety bandit
safety check -r webapp/requirements.txt
bandit -r scripts/ webapp/
```

#### 4. Minimize Dependencies
- Audit existing dependencies for necessity.
- Remove unused packages to reduce attack surface.
- Prefer stdlib (e.g., `json`, `sqlite3`) over external libraries where possible.

#### 5. Generate Software Bill of Materials (SBOM)
Document all dependencies for transparency and incident response:

```bash
pip install cyclonedx-bom
cyclonedx-bom -o requirements-sbom.xml
```

### Build & Release Integrity

#### 1. Signed Commits
Enforce signed commits from trusted contributors:
```bash
git config --global user.signingkey <KEY_ID>
git commit -S -m "message"
```

GitHub settings:
- Require signed commits on main branch (Branch Protection Rules)
- Dismiss stale PR approvals on new commits

#### 2. Artifact Verification
If distributing releases/containers:
- Sign container images with Cosign
- Sign release artifacts (tar.gz, wheels) with GPG
- Publish signatures and public keys in release notes

#### 3. CI/CD Security
Add to GitHub Actions workflow:
```yaml
- name: Run dependency audit
  run: |
    pip install safety
    safety check -r webapp/requirements.txt

- name: Run SAST scanning
  run: |
    pip install bandit
    bandit -r scripts/ webapp/ -f json -o bandit-report.json
```

### Developer Environment

#### 1. Pre-commit Hooks
Add `.pre-commit-config.yaml` to enforce security checks locally:
```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: detect-private-key
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-json
      - id: check-yaml

  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.5
    hooks:
      - id: bandit
        args: ['-c', '.bandit']
        files: ^(scripts|webapp)/
```

#### 2. Dependency Pinning & Lock Files
Maintain a lock file alongside `requirements.txt`:
- Lock file: frozen exact versions with hashes (checked into git)
- Dev requirement: allows flexible versions during development
- Production deployment: always uses lock file

#### 3. Contributor Onboarding
Document for contributors:
- Required: Sign commits with GPG
- Recommended: Use pre-commit hooks locally
- All PRs: Automatic security scanning via CI/CD

### Third-Party Risks

#### PyPI Package Risk
- **Risk:** Compromised or typosquatted packages on PyPI
- **Mitigation:**
  - Use exact version pinning (done ✅)
  - Verify package maintainers are trusted
  - Review package source code before updating
  - Monitor security advisories (e.g., [CVE Details](https://www.cvedetails.com/))

#### Transitive Dependency Risk
- **Risk:** Direct dependencies may pull in compromised sub-dependencies
- **Mitigation:**
  - `pip install pip-audit` and run regularly
  - Use lock files with hash verification
  - Pin sub-dependency versions in lock file if needed
  - Example: `pip-audit --desc` shows all transitive deps

#### Container/System Package Risk
If deploying in containers:
- Use minimal base image (e.g., `python:3.11-slim`)
- Scan container images for vulnerabilities:
  ```bash
  pip install trivy
  trivy image <image:tag>
  ```
- Keep OS packages updated (`apt update && apt upgrade`)

---

## Supply Chain Security Checklist

- [x] Enable Dependabot on GitHub for automatic vulnerability alerts.
- [ ] Generate and commit `webapp/requirements.lock` with hashes.
- [ ] Configure pip to require hash verification in production deployments.
- [ ] Add pre-commit hooks for dependency and security scanning.
- [ ] Run `pip-audit` and `safety check` in CI/CD pipeline.
- [ ] Require signed commits from all contributors on main branch.
- [ ] Document dependency rationale (why each package is necessary).
- [ ] Audit transitive dependencies monthly.
- [ ] Monitor security advisories for Flask, Gunicorn, and other key packages.
- [ ] Generate SBOM for releases.
- [ ] Set up alerts for new CVEs affecting pinned versions.
- [ ] Review and validate all dependency updates before merging PRs.

---

## Deployment Checklist

For production deployments, follow these steps:

- [ ] Use a production WSGI server (e.g., Gunicorn, uWSGI) instead of Flask's built-in server.
- [ ] Set `DEBUG=false` environment variable.
- [ ] Deploy behind an HTTPS reverse proxy (Nginx, Apache, etc.).
- [ ] Implement authentication (API keys or IP allowlisting).
- [ ] Enable rate limiting (Flask-Limiter or reverse proxy rules).
- [ ] Validate all input parameters against documented bounds.
- [ ] Set request timeouts (5–10 minutes recommended).
- [ ] Configure logging to capture requests and errors.
- [ ] Restrict database file permissions to application user only.
- [ ] Run regular security audits and dependency updates.
- [ ] Use environment variables for all sensitive configuration (no hardcoded secrets).
- [ ] Verify all dependencies with hash checking enabled.
- [ ] Scan container images for vulnerabilities (if containerized).
- [ ] Document and maintain an up-to-date SBOM.

---

## Docker Deployment Security

### Container Hardening

- [ ] Run container as non-root user (create dedicated app user)
- [ ] Use specific Python base image tag (e.g., `python:3.11.8-slim-bookworm` not `3.11-slim`)
- [ ] Add `.dockerignore` to exclude `.git`, `.env`, caches, and test files
- [ ] Implement HEALTHCHECK for orchestrator liveness detection
- [ ] Run with `--read-only` filesystem where possible; mount `/app/data` as writable volume only
- [ ] Set resource limits (memory: 512M, CPU: 1 core recommended)
- [ ] Use multi-stage builds to reduce final image size and attack surface

### Gunicorn Configuration

- [ ] Set `--workers` to `2 * CPU_CORES + 1` (currently hardcoded to 1)
- [ ] Add `--timeout 300` (5 minutes) to prevent hanging requests
- [ ] Enable `--access-logfile -` for centralized logging (already configured)
- [ ] Consider `--max-requests 1000` to recycle workers and prevent memory leaks
- [ ] Set `--worker-class gthread` (already configured) for concurrent request handling

### Image Security Scanning

- [ ] Scan built image with Trivy: `trivy image <image:tag>`
- [ ] Scan with Grype for additional CVE detection
- [ ] Pin all Python package versions in `requirements.txt` (already done)
- [ ] Regenerate requirements.txt periodically and rebuild images
- [ ] Use private container registry with image signing (Cosign)

### Orchestration (K8s / Docker Compose)

- [ ] Use network policies to restrict inter-pod communication
- [ ] Implement Pod Security Policies / Pod Security Standards (Kubernetes)
- [ ] Use secrets management (Kubernetes Secrets, HashiCorp Vault) for `PLOTTER_API_KEY` if added
- [ ] Enable audit logging for container runtime (containerd/Docker)
- [ ] Use immutable image tags in production (e.g., `plotter:v1.2.3` not `latest`)

---

## Reporting Security Issues

To report a new security issue privately, please open a [GitHub Security Advisory](https://github.com/cmdr-threethree/plotter/security/advisories/new).
