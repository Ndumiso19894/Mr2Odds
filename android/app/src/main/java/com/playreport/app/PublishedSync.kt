package com.playreport.app

import android.content.Context
import org.json.JSONObject

/**
 * Keeps the offline cache in sync with the server between app launches:
 * a cheap meta.json heartbeat (conditional, with 403/429 back-off) plus a latest.json
 * refresh with the same revalidation + back-off pattern. Runs from the 15-minute worker.
 */
object PublishedSync {

    private const val MIN_BACKOFF_MS = 15 * 60_000L   // WorkManager periodic floor
    private const val MAX_BACKOFF_MS = 24 * 3600_000L

    private fun backoff(retryAfter: Long, now: Long): Long =
        now + (maxOf(MIN_BACKOFF_MS, retryAfter).coerceAtMost(MAX_BACKOFF_MS))

    /** meta.json with conditional revalidation; returns 0/"cooldown" while in back-off. */
    fun heartbeat(context: Context): Net.Response {
        val shared = JsonCache.shared(context)
        val prefs = context.getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        if (now < prefs.getLong("cache_meta_after", 0L)) return Net.Response(0, "cooldown")

        val cached = try { shared.read(Net.META_JSON) } catch (e: Exception) { null }
        val response = Net.get(Net.META_JSON, etag = cached?.optString("etag")?.takeIf { it.isNotEmpty() },
                               modified = cached?.optString("modified")?.takeIf { it.isNotEmpty() })
        return when (response.code) {
            304 -> {
                val body = cached?.optString("body").orEmpty()
                if (body.isNotEmpty()) Net.Response(200, body) else response
            }
            200 -> {
                val meta = try { JSONObject(response.body) } catch (e: Exception) { null }
                if (meta != null && meta.optString("generated").isNotBlank()) {
                    val samePublished = cached?.let { runCatching { it.getString("body") }.getOrNull() == response.body } == true
                    if (samePublished) shared.touch(Net.META_JSON, now, response.etag, response.modified)
                    else {
                        shared.put(Net.META_JSON, JSONObject()
                            .put("body", response.body)
                            .put("etag", response.etag)
                            .put("modified", response.modified)
                            .put("checkedAt", now)
                            .put("updatedAt", now))
                    }
                }
                response
            }
            403, 429 -> {
                prefs.edit().putLong("cache_meta_after", backoff(response.retryAfter, now)).apply()
                response
            }
            else -> response
        }
    }

    /** latest.json sync after the heartbeat; validates shape before trusting the payload. */
    fun refresh(context: Context, meta: JSONObject) {
        if (meta.optString("generated").isBlank()) return
        val prefs = context.getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE)
        val now = System.currentTimeMillis()
        if (now < prefs.getLong("cache_sync_after", 0L)) return
        val shared = JsonCache.shared(context)
        val cached = try { shared.read(Net.LATEST_JSON) } catch (e: Exception) { null }
        if (cached?.optLong("retryAt") ?: 0L > now) return

        val response = Net.get(Net.LATEST_JSON, etag = cached?.optString("etag")?.takeIf { it.isNotEmpty() },
                               modified = cached?.optString("modified")?.takeIf { it.isNotEmpty() })
        when (response.code) {
            304 -> {
                if (cached != null) {
                    shared.touch(Net.LATEST_JSON, now, response.etag.takeIf { it.isNotEmpty() }, response.modified.takeIf { it.isNotEmpty() })
                    shared.failure(Net.LATEST_JSON, null)
                }
            }
            200 -> {
                val data = try { JSONObject(response.body) } catch (e: Exception) { null }
                if (data != null && JsonCache.validLatest(data)) {
                    val samePublished = cached?.let { runCatching { it.getString("body") }.getOrNull() == response.body } == true
                    if (samePublished) shared.touch(Net.LATEST_JSON, now, response.etag.takeIf { it.isNotEmpty() }, response.modified.takeIf { it.isNotEmpty() })
                    else {
                        shared.put(Net.LATEST_JSON, JSONObject()
                            .put("body", response.body)
                            .put("etag", response.etag)
                            .put("modified", response.modified)
                            .put("checkedAt", now)
                            .put("updatedAt", now))
                    }
                    shared.failure(Net.LATEST_JSON, null)
                }
            }
            else -> {
                val until = backoff(response.retryAfter, now)
                shared.failure(Net.LATEST_JSON, JSONObject().put("until", until).put("code", response.code).put("count", 1))
                prefs.edit().putLong("cache_sync_after", until).apply()
            }
        }
    }
}
