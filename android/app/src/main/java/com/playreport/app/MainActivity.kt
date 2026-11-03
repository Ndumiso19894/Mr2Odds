package com.playreport.app

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/**
 * Single-activity shell: a WebView running the bundled Mr 2 Odds web layer, plus the native
 * bridge the web app calls (`window.Android.*`): authenticated-feeling fetches (host-allowed),
 * the offline resource cache, notifications, theme, exports, and the self-update flow.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var web: WebView
    private lateinit var swipe: SwipeRefreshLayout
    private val pool = Executors.newFixedThreadPool(3)
    private val jsonCache by lazy { JsonCache.shared(applicationContext) }
    private var pendingTab: String? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var pendingSave: Pair<String, String>? = null
    private var pendingSaveBytes: Pair<String, ByteArray>? = null

    private val askNotifications: ActivityResultLauncher<String> =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
            js("window.app && window.app.onPermission && window.app.onPermission($ok);")
        }

    private val saveDocument: ActivityResultLauncher<String> =
        registerForActivityResult(ActivityResultContracts.CreateDocument("text/plain")) { uri ->
            val pair = pendingSave; pendingSave = null
            val target = uri
            if (pair == null || target == null) js("window.__saveDone && window.__saveDone(false);")
            else pool.execute {
                var ok = false
                try {
                    contentResolver.openOutputStream(target, "wt")?.use { out ->
                        out.write(pair.second.toByteArray())
                    }
                    ok = true
                } catch (e: Exception) {}
                js("window.__saveDone && window.__saveDone($ok);")
            }
        }

    private val saveDocumentBytes: ActivityResultLauncher<String> =
        registerForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri ->
            val pair = pendingSaveBytes; pendingSaveBytes = null
            val target = uri
            if (pair == null || target == null) js("window.__saveDone && window.__saveDone(false);")
            else pool.execute {
                var ok = false
                try {
                    contentResolver.openOutputStream(target)?.use { out -> out.write(pair.second) }
                    ok = true
                } catch (e: Exception) {}
                js("window.__saveDone && window.__saveDone($ok);")
            }
        }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifier.createChannels(this)
        scheduleChecks()

        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: android.net.Network) = js("window.PR && PR.connectionChanged && PR.connectionChanged();")
            override fun onLost(network: android.net.Network) = js("window.PR && PR.statusLine && PR.statusLine();")
        }
        networkCallback = callback
        runCatching { cm.registerDefaultNetworkCallback(callback) }

        swipe = SwipeRefreshLayout(this)
        web = WebView(this)
        applyTheme(getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE).getBoolean("dark", true))
        web.layoutParams = ViewGroup.LayoutParams(-1, -1)
        swipe.addView(web)
        setContentView(swipe)
        ViewCompat.setOnApplyWindowInsetsListener(swipe) { view, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(sys.left, sys.top, sys.right, sys.bottom)
            insets
        }

        val settings = web.settings
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.cacheMode = WebSettings.LOAD_DEFAULT
        web.addJavascriptInterface(Bridge(), "Android")
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val url = request.url.toString()
                if (url.startsWith("http") && !Security.nativeAllowed(url)) {
                    openExternal(request.url)
                    return true
                }
                return false
            }
            override fun onPageFinished(view: WebView, url: String) {
                val t = pendingTab
                if (t != null) {
                    pendingTab = null
                    handleTab(t)
                }
            }
        }
        swipe.setOnRefreshListener {
            js("window.app && app.refresh && app.refresh();")
            swipe.isRefreshing = false
        }

        savedInstanceState?.getString("tab")?.let { pendingTab = it }
        web.loadUrl("file:///android_asset/www/index.html")
        intent.getStringExtra("tab")?.let { t ->
            if (pendingTab == null) pendingTab = t
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        intent.getStringExtra("tab")?.let { handleTab(it) }
    }

    /** Route a notification tap / deep link into the web app. */
    private fun handleTab(t: String) {
        when {
            t == "install" -> startUpdateInstall()
            t.startsWith("match|") -> js("window.app && window.app.openNotifMatch && window.app.openNotifMatch(${JSONObject.quote(t)});")
            t.startsWith("tennis|") -> js("window.app && window.app.openNotifTennis && window.app.openNotifTennis(${JSONObject.quote(t)});")
            else -> js("window.app && window.app.setTab && window.app.setTab(${JSONObject.quote(t)});")
        }
    }

    private fun startUpdateInstall() {
        pool.execute {
            val info = Updater.check()
            if (info == null || !Updater.isNewer(info.version, BuildConfig.VERSION_NAME)) {
                js("window.__updateProgress && window.__updateProgress('failed');")
                return@execute
            }
            val file = Updater.download(this@MainActivity, info)
            if (file != null) {
                js("window.__updateInstalling && window.__updateInstalling();")
                if (!Updater.install(this@MainActivity, file) && !Updater.handOff(this@MainActivity, info)) {
                    js("window.__updateProgress && window.__updateProgress('failed');")
                }
            } else if (!Updater.handOff(this@MainActivity, info)) {
                js("window.__updateProgress && window.__updateProgress('failed');")
            } else {
                js("window.__updateProgress && window.__updateProgress('browser');")
            }
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
                js("window.app && window.app.onPermission && window.app.onPermission(true);")
            } else askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            js("window.app && window.app.onPermission && window.app.onPermission(true);")
        }
    }

    private fun scheduleChecks() {
        val request = PeriodicWorkRequest.Builder(CheckWorker::class.java, 15, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            CheckWorker.WORK_NAME, ExistingPeriodicWorkPolicy.UPDATE, request)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        pendingTab?.let { outState.putString("tab", it) }
    }

    override fun onResume() {
        super.onResume()
        js("window.app && window.app.onResume && window.app.onResume();")
    }

    override fun onDestroy() {
        networkCallback?.let { runCatching {
            (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager).unregisterNetworkCallback(it)
        } }
        pool.shutdown()
        super.onDestroy()
    }

    private fun openExternal(uri: Uri) {
        runCatching { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
    }

    private fun js(code: String) {
        runOnUiThread { try { web.evaluateJavascript(code, null) } catch (e: Exception) {} }
    }

    /** Dark/light theme: window + WebView backgrounds, bar appearance, persisted. */
    private fun applyTheme(dark: Boolean) {
        val bg = Color.parseColor(if (dark) "#0B0F14" else "#F2F4F8")
        web.setBackgroundColor(bg)
        swipe.setBackgroundColor(bg)
        window.navigationBarColor = if (dark) Color.parseColor("#0E131A") else Color.TRANSPARENT
        WindowInsetsControllerCompat(window, web).apply {
            isAppearanceLightNavigationBars = !dark
            isAppearanceLightStatusBars = false
        }
        getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE).edit().putBoolean("dark", dark).apply()
    }

    /** Everything the web layer may do natively. Hosts are allow-listed in Security. */
    inner class Bridge {

        @android.webkit.JavascriptInterface
        fun fetch(id: Int, url: String, userAgent: String?) {
            if (!Security.webAllowed(url)) {
                js("window.__fetchDone && window.__fetchDone($id, 0, ${JSONObject.quote("blocked host")});")
                return
            }
            pool.execute {
                val r = Net.get(url, userAgent ?: Net.UA)
                js("window.__fetchDone && window.__fetchDone($id, ${r.code}, ${JSONObject.quote(r.body)});")
            }
        }

        @android.webkit.JavascriptInterface
        fun fetchConditional(id: Int, url: String, userAgent: String?, etag: String?, modified: String?) {
            pool.execute {
                val r = if (Security.webAllowed(url))
                    Net.get(url, userAgent ?: Net.UA, etag = etag?.takeIf { it.isNotEmpty() }, modified = modified?.takeIf { it.isNotEmpty() })
                else Net.Response(0, "blocked host")
                val meta = JSONObject().put("etag", r.etag).put("modified", r.modified).put("retryAfter", r.retryAfter)
                js("window.__fetchDone && window.__fetchDone($id, ${r.code}, ${JSONObject.quote(r.body)}, $meta);")
            }
        }

        @android.webkit.JavascriptInterface
        fun online(): Boolean {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val net = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(net) ?: return false
            return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        }

        @android.webkit.JavascriptInterface
        fun cacheRead(id: Int, url: String) {
            pool.execute {
                val entry = try { jsonCache.read(url)?.toString() } catch (e: Exception) { null }
                js("window.__cacheDone && window.__cacheDone($id, ${JSONObject.quote(entry ?: "null")});")
            }
        }

        @android.webkit.JavascriptInterface
        fun cacheWrite(id: Int, url: String, entry: String) {
            pool.execute {
                val ok = try { jsonCache.put(url, JSONObject(entry)) } catch (e: Exception) { false }
                js("window.__cacheDone && window.__cacheDone($id, $ok);")
            }
        }

        @android.webkit.JavascriptInterface
        fun cacheTouch(id: Int, url: String, checked: Long, etag: String?, modified: String?) {
            pool.execute {
                val ok = jsonCache.touch(url, checked, etag?.takeIf { it.isNotEmpty() }, modified?.takeIf { it.isNotEmpty() })
                js("window.__cacheDone && window.__cacheDone($id, $ok);")
            }
        }

        @android.webkit.JavascriptInterface
        fun cacheFailure(id: Int, url: String, failure: String?) {
            pool.execute {
                val ok = try {
                    jsonCache.failure(url, failure?.takeIf { it != "null" }?.let { runCatching { JSONObject(it) }.getOrNull() })
                    true
                } catch (e: Exception) { false }
                js("window.__cacheDone && window.__cacheDone($id, $ok);")
            }
        }

        @android.webkit.JavascriptInterface
        fun cacheClear(id: Int) {
            jsonCache.invalidate()
            pool.execute {
                val ok = jsonCache.clear()
                js("window.__cacheDone && window.__cacheDone($id, $ok);")
            }
        }

        @android.webkit.JavascriptInterface
        fun refreshDone() {
            runOnUiThread { swipe.isRefreshing = false }
        }

        @android.webkit.JavascriptInterface
        fun openUrl(url: String) {
            runOnUiThread { runCatching { openExternal(Uri.parse(url)) } }
        }

        @android.webkit.JavascriptInterface
        fun share(text: String) {
            runOnUiThread {
                val intent = Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_TEXT, text)
                }
                runCatching { startActivity(Intent.createChooser(intent, "Share")) }
            }
        }

        @android.webkit.JavascriptInterface
        fun version(): String = BuildConfig.VERSION_NAME

        @android.webkit.JavascriptInterface
        fun dataUrl(): String = Net.LATEST_JSON

        @android.webkit.JavascriptInterface
        fun rawBase(): String = "https://raw.githubusercontent.com/${Net.REPO}/data/"

        @android.webkit.JavascriptInterface
        fun setPref(key: String, value: Boolean) {
            getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE).edit().putBoolean("pref_$key", value).apply()
        }

        @android.webkit.JavascriptInterface
        fun setString(key: String, value: String) {
            getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE).edit().putString("str_$key", value).apply()
        }

        @android.webkit.JavascriptInterface
        fun getString(key: String): String? =
            getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE).getString("str_$key", null)

        @android.webkit.JavascriptInterface
        fun saveText(name: String, mime: String, text: String) {
            pendingSave = name to text
            runCatching { saveDocument.launch(name) }
                .onFailure { js("window.__saveDone && window.__saveDone(false);") }
        }

        @android.webkit.JavascriptInterface
        fun saveBase64(name: String, mime: String, b64: String) {
            val bytes = try { java.util.Base64.decode(b64) } catch (e: Exception) { null }
            if (bytes == null) {
                js("window.__saveDone && window.__saveDone(false);")
                return
            }
            pendingSaveBytes = name to bytes
            runCatching { saveDocumentBytes.launch(name) }
                .onFailure { js("window.__saveDone && window.__saveDone(false);") }
        }

        @android.webkit.JavascriptInterface
        fun setTheme(dark: Boolean) {
            runOnUiThread { applyTheme(dark) }
        }

        @android.webkit.JavascriptInterface
        fun notificationsAllowed(): Boolean = runCatching { Notifier.allowed(this@MainActivity) }.getOrDefault(false)

        @android.webkit.JavascriptInterface
        fun requestNotifications() {
            requestNotificationPermission()
        }

        @android.webkit.JavascriptInterface
        fun notify(channel: String, id: Int, title: String, text: String, tab: String?) {
            Notifier.notify(this@MainActivity, channel, id, title, text, tab)
        }

        @android.webkit.JavascriptInterface
        fun openChannelSettings(channel: String) {
            val intent = Intent(android.provider.Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS).apply {
                putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, packageName)
                putExtra(android.provider.Settings.EXTRA_CHANNEL_ID, channel)
            }
            runCatching { startActivity(intent) }
                .onFailure { runCatching { startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                    data = Uri.parse("package:$packageName")
                }) } }
        }

        @android.webkit.JavascriptInterface
        fun notifyGoal(eid: String, score: String, title: String, text: String) {
            if (Notifier.goalSeen(this@MainActivity, eid, score)) return
            Notifier.notify(this@MainActivity, Notifier.CH_GOALS, eid.hashCode(), title, text, "live")
        }

        @android.webkit.JavascriptInterface
        fun markScore(eid: String, score: String) {
            Notifier.goalSeen(this@MainActivity, eid, score)
        }

        @android.webkit.JavascriptInterface
        fun checkUpdate() {
            pool.execute {
                val info = Updater.check()?.takeIf { Updater.isNewer(it.version, BuildConfig.VERSION_NAME) }
                if (info != null) Notifier.notifyUpdateOnce(this@MainActivity, info.version, info.notes)
                val payload = if (info != null)
                    JSONObject().put("version", info.version).put("url", info.url).put("notes", info.notes).toString()
                else "null"
                js("window.__updateInfo && window.__updateInfo($payload);")
            }
        }

        @android.webkit.JavascriptInterface
        fun installUpdate(url: String) {
            pool.execute {
                val info = Updater.check()
                if (info == null || info.url != url || !Updater.isNewer(info.version, BuildConfig.VERSION_NAME)) {
                    js("window.__updateProgress && window.__updateProgress('failed');")
                    return@execute
                }
                val file = Updater.download(this@MainActivity, info)
                if (file != null) {
                    js("window.__updateInstalling && window.__updateInstalling();")
                    if (!Updater.install(this@MainActivity, file)) {
                        if (Updater.handOff(this@MainActivity, info)) js("window.__updateProgress && window.__updateProgress('browser');")
                        else js("window.__updateProgress && window.__updateProgress('failed');")
                    }
                } else if (Updater.handOff(this@MainActivity, info)) {
                    js("window.__updateProgress && window.__updateProgress('browser');")
                } else {
                    js("window.__updateProgress && window.__updateProgress('failed');")
                }
            }
        }
    }
}
