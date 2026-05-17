# Analysis: Prefix Compression Trade-offs

This document estimates the trade-offs between the current prefix-compressed database schema and a flat (no-prefix) schema at a scale of **50 million systems** and **5 million unique prefixes**.

## 1. Database Size Trade-off

| Feature | Prefix-Compressed Schema | Flat Schema (Full Name) |
| :--- | :--- | :--- |
| **System Name Storage** | `prefix_id` (4-8 bytes) + `name_suffix` (avg. 5-10 bytes). | `name` (avg. 15-25 bytes). |
| **Prefix Table Overhead** | 5M rows (avg. 10 bytes/prefix) ≈ **50 MB**. | **0 MB** (No table). |
| **System Table Index** | Index on `(prefix_id, name_suffix)`. Very compact. | Index on `name` (string). Much larger. |
| **Total Estimated Size** | **~2.5 GB - 3.5 GB** | **~4.0 GB - 6.0 GB** |

**Estimation:** The prefix-compressed schema is approximately **30-50% smaller**. Storing millions of redundant strings (e.g., "HIP", "Colonia", "Pleiades Sector") as integer IDs significantly reduces the primary table size and the size of the associated indexes.

## 2. Query Efficiency Trade-off

| Feature | Prefix-Compressed Schema | Flat Schema (Full Name) |
| :--- | :--- | :--- |
| **Exact Search** | Requires splitting the query into candidate prefix/suffix pairs and checking an `IN` clause (O(N) where N is small, usually < 3 splits). | Direct `SELECT ... WHERE name = ?`. O(log N) on a large string index. |
| **Nearest/Path Results** | Requires a `JOIN` or secondary lookup to resolve the `prefix_id` to a string. | Name is available directly in the system row. |
| **Memory Usage** | Smallest working set. Page cache is more effective because rows are narrower. | Higher IO and memory pressure due to wider rows and larger indexes. |
| **Prefix Search (Typing)** | Efficient if we search for the prefix first. | Requires `LIKE 'prefix%'`, which is fast but creates a larger index footprint. |

**Estimation:**
*   **Search:** The flat schema is slightly faster for a single "point" lookup by name because it avoids the split-and-check logic. However, the prefix schema's `IN` clause against a `UNIQUE` index is extremely fast (sub-millisecond).
*   **Throughput:** The prefix schema provides **higher total throughput** because database pages are more densely packed. More systems fit into the same RAM footprint, reducing physical IO.

## 3. Conclusion

*   **Efficiency:** The prefix schema is a major advantage for storage and memory efficiency. At 50M systems, saving 10-15 bytes per row equates to 500MB-750MB in raw data savings, and significantly more in index space.
*   **Trade-off:** The primary cost is application-level complexity in managing the prefix table and splitting search queries.
*   **Recommendation:** For resource-constrained environments (Docker, low-cost VPS), the **prefix-compressed schema is superior** as it trades minor CPU overhead for a significantly smaller disk and RAM footprint.
