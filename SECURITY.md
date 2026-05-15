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

---

## Reporting Security Issues

To report a new security issue privately, please open a [GitHub Security Advisory](https://github.com/cmdr-threethree/plotter/security/advisories/new).
