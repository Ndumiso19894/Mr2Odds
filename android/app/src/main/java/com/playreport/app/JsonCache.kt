package com.playreport.app

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicLong

/**
 * SQLite-backed cache for published JSON.
 *
 * `resources` holds full responses (body + ETag/Last-Modified for conditional revalidation);
 * `failures` is a negative cache so a dead URL is not re-polled every check. The cache is
 * bounded (32 MB total, 8 MB per entry) and evicts oldest-checked first — latest.json is kept.
 *
 * `epoch()`/`invalidate()` guard against a put racing a full clear: readers pass the epoch
 * they started from, and a stale put is dropped.
 */
class JsonCache private constructor(context: Context) : SQLiteOpenHelper(context, DB_NAME, null, 1) {

    companion object {
        const val DB_NAME = "published-cache.db"
        const val MAX_BYTES = 32L * 1024 * 1024
        const val MAX_ENTRY = 8 * 1024 * 1024
        private const val MAX_FAILURES = 300

        @Volatile
        private var instance: JsonCache? = null

        fun shared(context: Context): JsonCache {
            instance?.let { return it }
            synchronized(this) {
                instance?.let { return it }
                return JsonCache(context.applicationContext).also { instance = it }
            }
        }

        /** latest.json shape gate — the cache only ever holds payloads the app can render. */
        fun validLatest(data: JSONObject): Boolean {
            val generated = data.optJSONObject("meta")?.optString("generated")
            if (generated == null || !generated.matches(Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}.*"))) return false
            if (data.optInt("version") < 3) return false
            if (data.optJSONObject("safe") == null || data.optJSONObject("picks") == null) return false
            if (data.optJSONObject("history") == null || data.optJSONArray("tracked") == null) return false
            return true
        }

        /** Only our data URLs may enter the cache (mirrors the JS host policy). */
        fun allowed(url: String): Boolean {
            if (!Security.webAllowed(url)) return false
            if (url.startsWith("https://raw.githubusercontent.com/${Net.REPO}/data/data/app/") && url.endsWith(".json")) return true
            if (url.startsWith("https://prod-public-api.livescore.com/v1/api/app/")) return true
            if (Regex("https://raw\\.githubusercontent\\.com/${Regex.escape(Net.REPO)}/data/reports/[0-9]{4}-[0-9]{2}-[0-9]{2}\\.md").matches(url)) return true
            return false
        }
    }

    private val generation = AtomicLong(0)

    fun epoch(): Long = generation.get()
    fun invalidate(): Long = generation.incrementAndGet()

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE failures (url TEXT PRIMARY KEY, until_time INTEGER NOT NULL, code TEXT NOT NULL, count INTEGER NOT NULL)")
        db.execSQL("CREATE TABLE resources (url TEXT PRIMARY KEY, body TEXT NOT NULL, etag TEXT NOT NULL, modified TEXT NOT NULL, " +
                "checked INTEGER NOT NULL, updated INTEGER NOT NULL, published TEXT NOT NULL, bytes INTEGER NOT NULL)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) { /* schema v1 — nothing to migrate */ }

    /** Stored entry as {body, etag, modified, checkedAt, updatedAt, published, retryAt?, errorCode?, failureCount?} or null. */
    fun read(url: String): JSONObject? {
        if (!allowed(url)) return null
        var entry: JSONObject? = null
        readableDatabase.rawQuery("SELECT body,etag,modified,checked,updated,published FROM resources WHERE url=?", arrayOf(url)).use { c ->
            if (c.moveToFirst()) {
                entry = JSONObject()
                    .put("body", c.getString(0))
                    .put("etag", c.getString(1))
                    .put("modified", c.getString(2))
                    .put("checkedAt", c.getLong(3))
                    .put("updatedAt", c.getLong(4))
                    .put("published", c.getString(5))
            }
        }
        readableDatabase.rawQuery("SELECT until_time,code,count FROM failures WHERE url=?", arrayOf(url)).use { c ->
            if (c.moveToFirst()) {
                val put = entry ?: JSONObject()
                put.put("retryAt", c.getLong(0))
                val code = c.getString(1)
                put.put("errorCode", code.toIntOrNull() ?: code)
                put.put("failureCount", c.getInt(2))
                entry = put
            }
        }
        return entry
    }

    /**
     * Upsert a response. [entry] = {body, etag, modified, checkedAt, updatedAt}.
     * Rejected when: host not allowed, body blank/too big, not JSON, or the published stamp
     * is older than what is already stored (no regressions). Evicts LRU entries to stay bounded.
     */
    fun put(url: String, entry: JSONObject, expectedEpoch: Long = epoch()): Boolean {
        if (!allowed(url)) return false
        val body = entry.optString("body")
        val bytes = body.toByteArray().size
        if (body.isBlank() || bytes > MAX_ENTRY || entry.optLong("checkedAt") <= 0L) return false
        val parsed: JSONObject = try { JSONObject(body) } catch (e: Exception) { return false }
        val published = parsed.optJSONObject("meta")?.optString("generated") ?: parsed.optString("generated")
        if (expectedEpoch != epoch()) return false
        return try {
            writableDatabase.transactionUse { db ->
                var storedPublished = ""
                db.rawQuery("SELECT published FROM resources WHERE url=?", arrayOf(url)).use { c ->
                    if (c.moveToFirst()) storedPublished = c.getString(0)
                }
                if (published.isNotBlank() && storedPublished.isNotBlank() && published < storedPublished) return@transactionUse false
                val values = ContentValues().apply {
                    put("url", url)
                    put("body", body)
                    put("etag", entry.optString("etag"))
                    put("modified", entry.optString("modified"))
                    put("published", published)
                    put("checked", entry.getLong("checkedAt"))
                    put("updated", entry.optLong("updatedAt").let { if (it > 0L) it else entry.getLong("checkedAt") })
                    put("bytes", bytes)
                }
                if (db.insertWithOnConflict("resources", null, values, SQLiteDatabase.CONFLICT_REPLACE) == -1L) return@transactionUse false
                // Evict oldest-checked (never latest.json) until under the budget.
                var total = db.rawQuery("SELECT COALESCE(SUM(bytes),0) FROM resources", null).use { c -> c.moveToFirst(); c.getLong(0) }
                db.rawQuery("SELECT url,bytes FROM resources WHERE url<>? AND url<>? ORDER BY checked ASC",
                        arrayOf(url, Net.LATEST_JSON)).use { c ->
                    while (total > MAX_BYTES && c.moveToNext()) {
                        db.delete("resources", "url=?", arrayOf(c.getString(0)))
                        total -= c.getLong(1)
                    }
                }
                true
            }
        } catch (e: Exception) {
            false
        }
    }

    /** Record a successful (re)check, optionally refreshing conditional headers (304 path). */
    fun touch(url: String, checked: Long, etag: String? = null, modified: String? = null): Boolean {
        return try {
            val values = ContentValues().apply {
                put("checked", checked)
                if (etag != null) put("etag", etag)
                if (modified != null) put("modified", modified)
            }
            writableDatabase.update("resources", values, "url=?", arrayOf(url)) > 0
        } catch (e: Exception) {
            false
        }
    }

    /** Record a failure ([value] = {until, code, count}) or clear it (null). Bounded to the newest 300. */
    fun failure(url: String, value: JSONObject?) {
        if (!allowed(url)) return
        try {
            val db = writableDatabase
            if (value == null) {
                db.delete("failures", "url=?", arrayOf(url))
                return
            }
            val values = ContentValues().apply {
                put("url", url)
                put("until_time", value.optLong("until"))
                put("code", value.optString("code"))
                put("count", value.optInt("count"))
            }
            db.insertWithOnConflict("failures", null, values, SQLiteDatabase.CONFLICT_REPLACE)
            db.execSQL("DELETE FROM failures WHERE url NOT IN (SELECT url FROM failures ORDER BY until_time DESC LIMIT $MAX_FAILURES)")
        } catch (e: Exception) {
            // never break a check over cache bookkeeping
        }
    }

    /** Drop everything (Settings → clear cache). Bumps the epoch so in-flight puts are dropped. */
    fun clear(): Boolean {
        return try {
            invalidate()
            val db = writableDatabase
            db.delete("resources", null, null)
            db.delete("failures", null, null)
            true
        } catch (e: Exception) {
            false
        }
    }

    private fun SQLiteDatabase.transactionUse(block: (SQLiteDatabase) -> Boolean): Boolean {
        beginTransaction()
        return try {
            val ok = block(this)
            setTransactionSuccessful()
            ok
        } catch (e: Exception) {
            false
        } finally {
            endTransaction()
        }
    }
}
