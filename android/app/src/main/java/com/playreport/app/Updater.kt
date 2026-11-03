package com.playreport.app

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File

/**
 * App self-update: checks the latest GitHub release, downloads the APK into the cache dir,
 * verifies its SHA-256 against the release-asset digest, and hands it to the package installer
 * via FileProvider. Falls back to the browser when the in-app path is unavailable.
 */
object Updater {

    data class Info(val version: String, val url: String, val notes: String, val sha256: String? = null)

    fun check(): Info? {
        val response = Net.get(Net.RELEASES_LATEST, accept = "application/vnd.github+json")
        if (response.code != 200) return null
        return try {
            val rel = JSONObject(response.body)
            val version = rel.optString("tag_name").removePrefix("app-v").removePrefix("v")
            var url = ""
            var sha: String? = null
            rel.optJSONArray("assets")?.let { assets ->
                for (i in 0 until assets.length()) {
                    val asset = assets.getJSONObject(i)
                    if (asset.optString("name").endsWith(".apk")) {
                        url = asset.optString("browser_download_url")
                        val digest = asset.optString("digest")
                        if (digest.startsWith("sha256:")) sha = digest.removePrefix("sha256:")
                    }
                }
            }
            if (url.isNotEmpty() && version.isNotEmpty() && Security.nativeAllowed(url)) {
                Info(version, url, rel.optString("body"), sha)
            } else null
        } catch (e: Exception) {
            null
        }
    }

    /** Numeric dot-segment comparison ("1.10.2" > "1.9.9"). */
    fun isNewer(candidate: String, current: String): Boolean {
        val parse = { s: String ->
            s.split(".").map { part ->
                val digits = part.filter { it.isDigit() }
                digits.toIntOrNull() ?: 0
            }
        }
        val a = parse(candidate); val b = parse(current)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }; val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    fun apkFile(ctx: Context): File = File(ctx.cacheDir, "updates/Mr2Odds.apk")

    /** Download + verify. Returns the verified APK file, or null on any failure (file cleaned up). */
    fun download(ctx: Context, info: Info): File? {
        if (!Security.nativeAllowed(info.url)) return null
        val target = apkFile(ctx)
        if (target.exists()) target.delete()
        if (!Net.download(info.url, target)) {
            target.delete()
            return null
        }
        val expected = info.sha256
        if (expected.isNullOrBlank() || expected.equals(Security.sha256(target), ignoreCase = true)) {
            return target
        }
        target.delete()
        return null
    }

    /** Open the download URL in the user's browser (fallback path). */
    fun handOff(ctx: Context, info: Info): Boolean {
        if (!Security.nativeAllowed(info.url)) return false
        return try {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(info.url)).apply {
                addCategory(Intent.CATEGORY_BROWSABLE)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            ctx.startActivity(intent)
            true
        } catch (e: Exception) {
            false
        }
    }

    /** Launch the package installer for a verified APK. */
    fun install(ctx: Context, file: File): Boolean {
        return try {
            val uri = FileProvider.getUriForFile(ctx, "${ctx.packageName}.fileprovider", file)
            val intent = Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(uri, "application/vnd.android.package-archive")
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
                clipData = ClipData.newRawUri("Mr 2 Odds update", uri)
            }
            ctx.startActivity(intent)
            true
        } catch (e: Exception) {
            false
        }
    }
}
