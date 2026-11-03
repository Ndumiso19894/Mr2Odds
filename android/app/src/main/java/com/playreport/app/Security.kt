package com.playreport.app

import android.net.Uri
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest
import java.util.Locale

/**
 * URL allow-lists + integrity helper. The WebView may only fetch hosts that publish our data;
 * native fetches (downloads, updates) additionally reach the release hosts.
 */
object Security {
    val WEB_HOSTS = setOf(
        "raw.githubusercontent.com",
        "api.github.com",
        "prod-public-api.livescore.com",
        "lsm-static-prod.livescore.com"
    )
    val NATIVE_HOSTS = WEB_HOSTS + setOf("github.com", "objects.githubusercontent.com")

    fun webAllowed(url: String): Boolean = allowed(url, WEB_HOSTS)
    fun nativeAllowed(url: String): Boolean = allowed(url, NATIVE_HOSTS)

    private fun allowed(url: String?, hosts: Set<String>): Boolean {
        if (url.isNullOrBlank()) return false
        val u = url.trim()
        if (!u.startsWith("https://", ignoreCase = true)) return false
        val rest = u.substring(8)
        if (rest.isEmpty() || rest.startsWith("/")) return false
        val hostPart = rest.substringBefore('/').substringBefore('?').substringBefore('#')
        if (hostPart.isEmpty() || hostPart.contains('@') || hostPart.contains('\\')) return false
        val host = hostPart.substringBefore(':').lowercase(Locale.ROOT)
        val port = hostPart.substringAfter(':', "")
        return if (port.isEmpty()) host in hosts else false
    }

    fun sha256(file: File): String? {
        return try {
            val digest = MessageDigest.getInstance("SHA-256")
            FileInputStream(file).use { input ->
                val buf = ByteArray(65_536)
                while (true) {
                    val n = input.read(buf)
                    if (n <= 0) break
                    digest.update(buf, 0, n)
                }
            }
            digest.digest().joinToString("") { "%02x".format(it) }
        } catch (e: Exception) {
            null
        }
    }
}
