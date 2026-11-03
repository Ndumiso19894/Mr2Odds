package com.playreport.app

import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/** Minimal HTTP helpers shared by the WebView bridge, the background checker and the updater. */
object Net {
    const val UA = "Mozilla/5.0 (Windows NT 10.0; Win32; x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

    /** Where the published analysis lives. Not shown anywhere in the UI. */
    val REPO: String = BuildConfig.REPO
    const val BRANCH = "data"
    val LATEST_JSON get() = "https://raw.githubusercontent.com/$REPO/$BRANCH/data/app/latest.json"
    val META_JSON get() = "https://raw.githubusercontent.com/$REPO/$BRANCH/data/app/meta.json"
    val ALERTS_JSON get() = "https://raw.githubusercontent.com/$REPO/$BRANCH/data/app/alerts.json"
    val RELEASES_LATEST get() = "https://api.github.com/repos/$REPO/releases/latest"

    /** Response body plus the cache-conditional headers the resource cache needs. */
    data class Response(val code: Int, val body: String, val etag: String = "", val modified: String = "", val retryAfter: Long = 0)

    /** In-flight de-duplication: concurrent identical requests share one network call. */
    private val pending = ConcurrentHashMap<String, CompletableFuture<Response>>()

    fun get(url: String, userAgent: String = UA, accept: String = "application/json, text/plain, */*",
            etag: String? = null, modified: String? = null): Response {
        val key = listOf(url, userAgent, accept, etag.orEmpty(), modified.orEmpty()).joinToString("\n")
        val own = CompletableFuture<Response>()
        val slot = pending.putIfAbsent(key, own)
        if (slot !== own) {
            try { return slot.get(50, TimeUnit.SECONDS) } catch (_: Exception) { return Response(0, "request timeout") }
        }
        try {
            val r = request(url, userAgent, accept, etag, modified)
            slot.complete(r)
            return r
        } catch (e: Exception) {
            slot.complete(Response(0, e.message ?: "network error"))
            return Response(0, e.message ?: "network error")
        } finally {
            pending.remove(key)
        }
    }

    private fun request(url: String, userAgent: String, accept: String, etag: String?, modified: String?): Response {
        val conn = open(url, userAgent, accept)
        if (etag != null) conn.setRequestProperty("If-None-Match", etag)
        if (modified != null) conn.setRequestProperty("If-Modified-Since", modified)
        val code = try { conn.responseCode } catch (e: Exception) { conn.disconnect(); throw e }
        return try {
            when (code) {
                304 -> Response(304, "", etag.orEmpty(), modified.orEmpty())
                else -> {
                    val stream = if (code < 400) conn.inputStream else conn.errorStream
                    val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
                    Response(code, body, conn.getHeaderField("ETag").orEmpty(), conn.getHeaderField("Last-Modified").orEmpty(),
                             runCatching { conn.getHeaderField("Retry-After")?.toLong() ?: 0L }.getOrDefault(0))
                }
            }
        } finally {
            conn.disconnect()
        }
    }

    /** Download to a file (used by the updater); returns false on any failure. */
    fun download(url: String, target: File): Boolean {
        return try {
            val conn = open(url, UA, "*/*")
            val code = conn.responseCode
            if (code !in 200..299) { conn.disconnect(); false }
            else {
                target.parentFile?.mkdirs()
                conn.inputStream.use { input -> target.outputStream().use { output -> input.copyTo(output) } }
                true
            }
        } catch (e: Exception) {
            false
        }
    }

    private fun open(url: String, userAgent: String, accept: String): HttpURLConnection {
        val conn = (URL(url).openConnection() as HttpURLConnection)
        conn.connectTimeout = 15_000
        conn.readTimeout = 30_000
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("User-Agent", userAgent)
        conn.setRequestProperty("Accept", accept)
        conn.setRequestProperty("Accept-Language", "en")
        return conn
    }
}
