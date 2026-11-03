package com.playreport.app

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat

/**
 * Notification channels + posting. Channels are versioned (_v4) and the previous generations
 * are deleted so the user never sees duplicates. Tapping a notification opens the app on the
 * matching tab via the `tab` intent extra.
 */
object Notifier {
    const val CH_REPORTS = "reports_v4"
    const val CH_GOALS = "goals_v4"
    const val CH_BETS = "bets_v4"
    const val CH_KICKOFF = "kickoff_v4"
    const val CH_MATCH = "match_v4"
    const val CH_TENNIS = "tennis_v4"
    const val CH_TICKETS = "tickets_v4"
    const val CH_UPDATES = "updates_v2"

    const val PREFS = "playreport"

    private val OLD_CHANNELS = listOf(
        "reports", "goals", "bets", "match", "updates", "kickoff", "tennis", "tickets",
        "reports_v2", "goals_v2", "bets_v2", "match_v2", "kickoff_v2",
        "reports_v3", "goals_v3", "bets_v3", "match_v3", "kickoff_v3", "tennis_v3", "tickets_v3"
    )

    private val soundAttrs = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_NOTIFICATION)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
        .build()

    private fun sound(ctx: Context, name: String): Uri =
        Uri.parse("android.resource://${ctx.packageName}/raw/$name")

    private fun channel(ctx: Context, id: String, name: String, importance: Int, desc: String,
                        soundName: String? = null, vibrate: Boolean = false): NotificationChannel {
        val ch = NotificationChannel(id, name, importance)
        ch.description = desc
        soundName?.let { ch.setSound(sound(ctx, it), soundAttrs) }
        ch.enableVibration(vibrate)
        if (vibrate) ch.vibrationPattern = longArrayOf(0, 180, 90, 180)
        return ch
    }

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        for (old in OLD_CHANNELS) { try { nm.deleteNotificationChannel(old) } catch (_: Exception) {} }
        nm.createNotificationChannel(channel(ctx, CH_REPORTS, "New analysis", NotificationManager.IMPORTANCE_DEFAULT,
            "A new Mr 2 Odds analysis has been published", "pr_report"))
        nm.createNotificationChannel(channel(ctx, CH_GOALS, "Goals in tracked matches", NotificationManager.IMPORTANCE_HIGH,
            "Score changes in tracked and shortlisted matches", "pr_goal", vibrate = true))
        nm.createNotificationChannel(channel(ctx, CH_BETS, "New selections & tickets", NotificationManager.IMPORTANCE_HIGH,
            "A new high-probability selection was found; one of your tickets was settled", "pr_selection", vibrate = true))
        nm.createNotificationChannel(channel(ctx, CH_KICKOFF, "Kick-off reminders", NotificationManager.IMPORTANCE_DEFAULT,
            "A tracked or favourite match is about to start", "pr_kickoff", vibrate = true))
        nm.createNotificationChannel(channel(ctx, CH_MATCH, "Half-time & full-time", NotificationManager.IMPORTANCE_DEFAULT,
            "Half-time and full-time scores of tracked matches", "pr_fulltime"))
        nm.createNotificationChannel(channel(ctx, CH_TENNIS, "Tennis live & results", NotificationManager.IMPORTANCE_HIGH,
            "Finished matches and kick-offs of your tennis favourites", "pr_tennis", vibrate = true))
        nm.createNotificationChannel(channel(ctx, CH_TICKETS, "Ticket results", NotificationManager.IMPORTANCE_HIGH,
            "One of your locked tickets was settled — won or lost", "pr_tickets", vibrate = true))
        nm.createNotificationChannel(channel(ctx, CH_UPDATES, "App updates", NotificationManager.IMPORTANCE_HIGH,
            "A newer version is available — tap to download it, then tap Install", "pr_report", vibrate = true))
    }

    fun soundFor(channel: String): String? = when (channel) {
        CH_REPORTS, CH_UPDATES -> "pr_report"
        CH_GOALS -> "pr_goal"
        CH_BETS -> "pr_selection"
        CH_KICKOFF -> "pr_kickoff"
        CH_MATCH -> "pr_fulltime"
        CH_TENNIS -> "pr_tennis"
        CH_TICKETS -> "pr_tickets"
        else -> null
    }

    /** Post a notification; [tab] (when non-null) is where a tap should land inside the app. */
    fun notify(ctx: Context, ch: String, id: Int, title: String, text: String, tab: String? = null) {
        try {
            val intent = Intent(ctx, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra("tab", tab)
            }
            val n = NotificationCompat.Builder(ctx, ch)
                .setSmallIcon(R.drawable.ic_stat_ball)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(NotificationCompat.BigTextStyle().bigText(text))
                .setAutoCancel(true)
                .setContentIntent(android.app.PendingIntent.getActivity(ctx, id, intent,
                    android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE))
                .build()
            NotificationManagerCompat.from(ctx).notify(id, n)
        } catch (e: Exception) {
            // never crash a check over a notification
        }
    }

    /** True when this eid+score combination has already been announced. */
    fun goalSeen(ctx: Context, eid: String, score: String): Boolean {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val key = "score_$eid"
        val seen = prefs.getString(key, null)
        if (seen == score) return true
        prefs.edit().putString(key, score).apply()
        return false
    }

    /** Announce an app update at most once per version; release notes are cleaned of markdown. */
    fun notifyUpdateOnce(ctx: Context, version: String, notes: String) {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (prefs.getString("update_notified", null) == version) return
        prefs.edit().putString("update_notified", version).apply()
        val lines = notes.lines()
            .map { it.trim().trimStart('-', '*', '•', ' ').trim() }
            .filter { it.isNotBlank() && !it.startsWith("#") && !it.startsWith("Download") }
            .take(10)
        val body = if (lines.isEmpty()) "What's new in this release." else lines.joinToString("\n")
        notify(ctx, CH_UPDATES, 9000, "Update available — $version", body)
    }

    fun allowed(ctx: Context): Boolean =
        NotificationManagerCompat.from(ctx).areNotificationsEnabled()
}
