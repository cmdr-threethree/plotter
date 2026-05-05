# Security

## Known Vulnerabilities

### CRITICAL — Path Traversal (`webapp/app.py`)

The `/api/search`, `/api/path`, and `/api/path_stream` endpoints accept `db` and `meta` query parameters and open them as file paths without validation:

```python
db = request.args.get('db', DB_PATH)
meta_path = request.args.get('meta', META_PATH)
with open(meta_path, 'r', encoding='utf-8') as mf: ...
distance.open_db(db)
```

An attacker can read arbitrary files the process has access to (e.g. `/etc/shadow`, SSH keys, other SQLite databases).

**Fix:** Remove user-controlled path parameters, or validate the resolved path against an allowlisted base directory using `os.path.realpath()`.

---

### HIGH — XSS via innerHTML (`webapp/static/app.js`)

System names and star types returned from the API are inserted directly into the DOM using `innerHTML` without escaping:

```javascript
li.innerHTML = `<strong>${i+1}) ${p.name}</strong> ... mainStar=${p.mainStar || ''}`;
```

A malicious system name in the database can execute arbitrary JavaScript in users' browsers.

**Fix:** Use `textContent` or build the element tree with `document.createElement` / `document.createTextNode` instead of `innerHTML`.

---

### MEDIUM — Flask Debug Mode Always Enabled (`webapp/app.py`)

The development server is started with `debug=True` unconditionally:

```python
app.run(host='0.0.0.0', port=port, debug=True)
```

Flask's debug mode exposes an interactive Python REPL accessible over the network, which allows arbitrary code execution.

**Fix:** Gate debug mode on an environment variable and use a production WSGI server (e.g. Gunicorn) instead of Flask's built-in server:

```python
debug = os.environ.get('DEBUG', 'false').lower() == 'true'
app.run(host='0.0.0.0', port=port, debug=debug)
```

---

### MEDIUM — SQL Query Built with f-string (`scripts/distance_cli_sqlite_prefix.py`)

A SQL query is partially constructed via an f-string, mixing parameterised placeholders with string interpolation:

```python
placeholders = ','.join('?' for _ in type_ids)
sql = f"SELECT ... WHERE star_type_id IN ({placeholders}) ..."
```

While `type_ids` is currently derived from an internal lookup, the f-string pattern is fragile and becomes a SQL injection vector if the data source ever changes.

**Fix:** Build the query with plain string concatenation rather than an f-string:

```python
sql = "SELECT ... WHERE star_type_id IN (" + placeholders + ") ..."
```

---

## Reporting

To report a new security issue privately, please open a [GitHub Security Advisory](https://github.com/cmdr-threethree/plotter/security/advisories/new).
