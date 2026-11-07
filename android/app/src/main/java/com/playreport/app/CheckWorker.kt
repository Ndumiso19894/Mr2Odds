package com.playreport.app

import android.content.Context
import android.content.SharedPreferences
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.Duration

/**
 * 15-minute background check (WorkManager):
 *  1. meta.json heartbeat + latest.json refresh (offline cache stays warm between launches);
 *  2. notify on a new analysis run / shortlist publication;
 *  3. notify on new high-probability alerts (server-pushed, de-duped);
 *  4. live scores for tracked matches: kick-off reminders, goals, half/full-time, tennis results;
 *  5. settle the user's tickets from live scores and notify winners/losers;
 *  6. app-update check (notify once per version).
 *
 * Every section is independently guarded — one bad source never kills the scan.
 */
class CheckWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    data class Ev(val eid: String, val status: String, val hg: Int?, val ag: Int?,
                  val home: String, val away: String, val comp: String)
    data class TNev(val eid: String, val finished: Boolean, val status: String,
                    val winner: Int?, val sets: Array<IntArray>)

    companion object {
        const val WORK_NAME = "playreport-check"
        private val SAST = ZoneId.of("Africa/Johannesburg")
        private val KICKOFF_FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm")

        fun isFinished(st: String): Boolean = st in setOf("FT", "AET", "AP", "Awarded")
        fun isVoid(st: String): Boolean = st in setOf("Postp.", "Canc.", "Aband.")
    }

    override suspend fun doWork(): Result {
        val ctx = applicationContext
        val prefs = ctx.getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE)
        try {
            val response = PublishedSync.heartbeat(ctx)
            val meta = if (response.code == 200) try { JSONObject(response.body) } catch (e: Exception) { JSONObject() } else JSONObject()
            try { PublishedSync.refresh(ctx, meta) } catch (e: Exception) {}

            // New analysis run published?
            try {
                val generated = meta.optString("generated")
                val last = prefs.getString("last_generated", null)
                if (generated != last) {
                    prefs.edit().putString("last_generated", generated).apply()
                    if (last != null && prefs.getBoolean("pref_reports", true)) {
                        val run = meta.optString("run")
                        val runLabel = if (run.startsWith("manual") || run.startsWith("auto")) "update" else "$run run"
                        val botd = meta.optJSONArray("botd")?.length() ?: 0
                        Notifier.notify(ctx, Notifier.CH_REPORTS, 2,
                            "New Mr 2 Odds analysis ($runLabel)",
                            "${meta.optInt("safe_bets")} high-probability selections · $botd bets of the day · ${meta.optInt("fixtures")} fixtures worldwide",
                            "home")
                    }
                }
                val shortlist = meta.optJSONObject("counts_shortlist") ?: JSONObject()
                val primary = shortlist.optInt("primary", -1)
                val lastShort = prefs.getString("last_shortlist_gen", null)
                if (primary >= 0 && generated != lastShort) {
                    prefs.edit().putString("last_shortlist_gen", generated).apply()
                    if (lastShort != null && prefs.getBoolean("pref_reports", true)) {
                        Notifier.notify(ctx, Notifier.CH_REPORTS, 3,
                            "🎯 Shortlist is live — $primary pick(s)",
                            "Strongest market per match, data-written analysis on every pick · tap to review",
                            "shortlist")
                    }
                }
            } catch (e: Exception) {}

            try { checkAlerts(ctx, meta) } catch (e: Exception) {}
            try { checkMatches(ctx, meta) } catch (e: Exception) {}

            try {
                val info = Updater.check()
                if (info != null && Updater.isNewer(info.version, BuildConfig.VERSION_NAME)) {
                    Notifier.notifyUpdateOnce(ctx, info.version, info.notes)
                }
            } catch (e: Exception) {}
        } catch (e: Exception) {
            return Result.retry()
        }
        return Result.success()
    }

    /** Server-pushed alerts (new high-probability selections); de-duped via the last 20 seen ids. */
    private fun checkAlerts(ctx: Context, meta: JSONObject) {
        val prefs = ctx.getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE)
        val ids = meta.optJSONArray("alerts") ?: return
        val seen = prefs.getString("alerts_seen", null)
            ?.split("\n")?.filter { it.isNotEmpty() }?.toMutableSet() ?: mutableSetOf()
        val fresh = mutableListOf<String>()
        for (i in 0 until ids.length()) {
            val id = ids.getString(i)
            if (id.isNotEmpty() && id !in seen) fresh.add(id)
        }
        if (fresh.isEmpty()) return
        seen.addAll(fresh)
        prefs.edit().putString("alerts_seen", seen.toList().takeLast(20).joinToString("\n")).apply()
        if (!prefs.getBoolean("pref_bets", true)) return
        if (seen.isEmpty()) return
        val response = Net.get(Net.ALERTS_JSON + "?t=" + System.currentTimeMillis())
        if (response.code != 200) return
        val list = try { JSONArray(response.body) } catch (e: Exception) { return }
        val byId = HashMap<String, JSONObject>()
        for (i in 0 until list.length()) {
            val a = list.getJSONObject(i)
            byId[a.optString("id")] = a
        }
        val newAlerts = fresh.mapNotNull { byId[it] }
        if (newAlerts.isEmpty()) return
        if (newAlerts.size <= 4) {
            for (a in newAlerts) {
                Notifier.notify(ctx, Notifier.CH_BETS, (a.optString("id").hashCode() and 4095) + 2000,
                    a.optString("title").takeIf { it.isNotEmpty() } ?: "New high-probability selection",
                    a.optString("text"), selectionLink(a))
            }
        } else {
            val lines = newAlerts.take(6).joinToString("\n") { it.optString("title") } +
                    (if (newAlerts.size > 6) "\n…and ${newAlerts.size - 6} more" else "")
            Notifier.notify(ctx, Notifier.CH_BETS, 2001, "${newAlerts.size} new high-probability selections", lines, "safest")
        }
    }

    private fun selectionLink(a: JSONObject): String {
        val fixture = a.optString("fixture")
        return if (fixture.isEmpty() || fixture == "null") "safest" else "match|$fixture"
    }

    /** Kick-off reminders, live goals, half/full-time, tennis results, and ticket settlement. */
    private fun checkMatches(ctx: Context, meta: JSONObject) {
        val prefs = ctx.getSharedPreferences(Notifier.PREFS, Context.MODE_PRIVATE)
        val wantGoals = prefs.getBoolean("pref_goals", true)
        val wantHT = prefs.getBoolean("pref_ht", false)
        val wantFT = prefs.getBoolean("pref_ft", true)
        val wantKO = prefs.getBoolean("pref_ko", true)

        val tickets = try { JSONArray(prefs.getString("str_tickets", "[]") ?: "[]") } catch (e: Exception) { JSONArray() }
        val favs = try { JSONArray(prefs.getString("str_favs", "[]") ?: "[]") } catch (e: Exception) { JSONArray() }

        // Tracked event ids: server-tracked + every ticket leg.
        val track = mutableSetOf<String>()
        meta.optJSONArray("tracked_eids")?.let { arr ->
            for (i in 0 until arr.length()) {
                val id = arr.optString(i)
                if (id.isNotEmpty()) track.add(id)
            }
        }
        for (t in 0 until tickets.length()) {
            val legs = tickets.getJSONObject(t).optJSONArray("legs") ?: continue
            for (i in 0 until legs.length()) {
                val eid = legs.getJSONObject(i).optString("eid")
                if (eid.isNotEmpty()) track.add(eid)
            }
        }

        // Kick-off reminders (0–21 min out), once per match.
        if (wantKO) {
            val now = LocalDateTime.now(SAST)
            for (i in 0 until favs.length()) {
                val f = favs.getJSONObject(i)
                if (f.optString("sport") == "tennis") continue // tennis is paused
                val eid = f.optString("eid")
                if (eid.isEmpty() || prefs.getBoolean("ko_$eid", false)) continue
                val kickoff = try { LocalDateTime.parse(f.optString("kickoff"), KICKOFF_FMT) } catch (e: Exception) { null } ?: continue
                val mins = Duration.between(now, kickoff).toMinutes()
                if (mins in 0..20) {
                    prefs.edit().putBoolean("ko_$eid", true).apply()
                    val isTennis = f.optString("sport") == "tennis"
                    val comp = f.optString("competition").takeIf { it.isNotEmpty() } ?: f.optString("league")
                    Notifier.notify(ctx, Notifier.CH_KICKOFF, (eid.hashCode() and 4095) + 7000,
                        "⏰ Kick-off in $mins min · ${f.optString("home")} v ${f.optString("away")}",
                        comp, if (isTennis) "tennis|$eid" else "football|$eid")
                }
            }
        }

        // Soccer live scores.
        val soccer = HashMap<String, Ev>()
        try {
            val day = LocalDate.now(SAST).format(DateTimeFormatter.ofPattern("yyyyMMdd"))
            val response = Net.get("https://prod-public-api.livescore.com/v1/api/app/date/soccer/$day/2?MD=1")
            if (response.code == 200) {
                val root = JSONObject(response.body)
                for (s in 0 until (root.optJSONArray("Stages")?.length() ?: 0)) {
                    val events = root.getJSONArray("Stages").getJSONObject(s).optJSONArray("Events") ?: continue
                    for (e in 0 until events.length()) {
                        val ev = events.getJSONObject(e)
                        val eid = ev.optString("Eid")
                        if (eid.isEmpty()) continue
                        val home = ev.optJSONArray("T1")?.optJSONObject(0)?.optString("Nm").orEmpty()
                        val away = ev.optJSONArray("T2")?.optJSONObject(0)?.optString("Nm").orEmpty()
                        val comp = ev.optJSONArray("T1")?.optJSONObject(0)?.let { t ->
                            listOf(t.optString("Cnm"), t.optString("Snm")).filter { it.isNotEmpty() }.joinToString(" · ")
                        }.orEmpty()
                        soccer[eid] = Ev(eid, ev.optString("Eps"),
                            ev.optString("Tr1").toIntOrNull(), ev.optString("Tr2").toIntOrNull(), home, away, comp)
                    }
                }
            }
        } catch (e: Exception) {}

        for (eid in track) {
            val ev = soccer[eid] ?: continue
            val score = if (ev.hg != null && ev.ag != null) "${ev.hg}-${ev.ag}" else null
            if (wantGoals && score != null && ev.hg != null && ev.ag != null &&
                ev.hg + ev.ag > 0 && !isFinished(ev.status) && !Notifier.goalSeen(ctx, eid, score)) {
                val scorer = latestScorer(eid)
                Notifier.notify(ctx, Notifier.CH_GOALS, (eid.hashCode() and 4095) + 3000,
                    "⚽ GOAL  ${ev.home} ${ev.hg} – ${ev.ag} ${ev.away}",
                    buildString {
                        if (scorer.isNotEmpty()) append(scorer).append(" · ")
                        append(ev.status).append(" · ").append(ev.comp)
                    }, "football|$eid")
            }
            if (wantHT && ev.status == "HT" && !prefs.getBoolean("ht_$eid", false)) {
                prefs.edit().putBoolean("ht_$eid", true).apply()
                Notifier.notify(ctx, Notifier.CH_MATCH, (eid.hashCode() and 4095) + 5000,
                    "⏸ Half-time  ${ev.home} ${ev.hg}-${ev.ag} ${ev.away}", ev.comp, "football|$eid")
            }
            if (wantFT && isFinished(ev.status) && !prefs.getBoolean("ft_$eid", false)) {
                prefs.edit().putBoolean("ft_$eid", true).apply()
                Notifier.notify(ctx, Notifier.CH_MATCH, (eid.hashCode() and 4095) + 6000,
                    "🏁 Full-time  ${ev.home} ${ev.hg}-${ev.ag} ${ev.away}", ev.comp, "football|$eid")
            }
        }

        // A ticket can refer to an earlier day, and corner counts arrive after
        // full time. Load the published day records for pending football legs,
        // including older tickets, without treating absent data as a result.
        val archiveById = HashMap<String, JSONObject>()
        val archiveByEid = HashMap<String, JSONObject>()
        val ambiguousEids = mutableSetOf<String>()
        val today = LocalDate.now(SAST)
        val dates = mutableSetOf<LocalDate>()
        for (t in 0 until tickets.length()) {
            val legs = tickets.getJSONObject(t).optJSONArray("legs") ?: continue
            for (i in 0 until legs.length()) {
                val leg = legs.getJSONObject(i)
                if (leg.optString("sport") == "tennis") continue
                val date = runCatching { LocalDate.parse(leg.optString("kickoff").take(10)) }.getOrNull() ?: continue
                if (!date.isAfter(today) && !date.isBefore(today.minusDays(60))) dates.add(date)
            }
        }
        val orderedDates = dates.sortedDescending()
        if (orderedDates.isNotEmpty()) {
            // Spread old pending dates over successive 15-minute checks rather
            // than making an unbounded number of network requests in one run.
            val offset = ((System.currentTimeMillis() / 900_000L) % orderedDates.size).toInt()
            for (n in 0 until minOf(8, orderedDates.size)) {
                val date = orderedDates[(offset + n) % orderedDates.size]
                val response = Net.get("https://raw.githubusercontent.com/${Net.REPO}/${Net.BRANCH}/data/app/days/$date.json?t=${System.currentTimeMillis() / 300_000L}")
                if (response.code != 200) continue
                val day = runCatching { JSONObject(response.body) }.getOrNull() ?: continue
                if (day.optString("date") != date.toString()) continue
                val fixtures = day.optJSONArray("fixtures") ?: continue
                for (i in 0 until fixtures.length()) {
                    val fixture = fixtures.optJSONObject(i) ?: continue
                    val id = fixture.optString("id")
                    val eid = fixture.optString("livescore_id")
                    if (id.isNotEmpty()) archiveById[id] = fixture
                    if (eid.isNotEmpty() && eid != "null") {
                        if (archiveByEid.containsKey(eid)) ambiguousEids.add(eid) else archiveByEid[eid] = fixture
                    }
                }
            }
        }

        // Only fetch tennis while an existing ticket still needs its results; no new scans or alerts.
        val tennis = HashMap<String, TNev>()
        val hasTennisTicket = (0 until tickets.length()).any { t ->
            val legs = tickets.getJSONObject(t).optJSONArray("legs")
            legs != null && (0 until legs.length()).any { i -> legs.getJSONObject(i).optString("sport") == "tennis" }
        }
        if (hasTennisTicket) try {
            val day = LocalDate.now(SAST).format(DateTimeFormatter.ofPattern("yyyyMMdd"))
            val response = Net.get("https://prod-public-api.livescore.com/v1/api/app/date/tennis/$day/2?MD=1")
            if (response.code == 200) {
                val root = JSONObject(response.body)
                for (s in 0 until (root.optJSONArray("Stages")?.length() ?: 0)) {
                    val events = root.getJSONArray("Stages").getJSONObject(s).optJSONArray("Events") ?: continue
                    for (e in 0 until events.length()) {
                        val ev = events.getJSONObject(e)
                        val eid = ev.optString("Eid")
                        if (eid.isEmpty()) continue
                        val status = ev.optString("Eps")
                        val finished = ev.optInt("Ewt") == 2 || status == "FT"
                        val p1 = ev.optJSONArray("T1")?.optJSONObject(0)?.optString("Nm").orEmpty()
                        val p2 = ev.optJSONArray("T2")?.optJSONObject(0)?.optString("Nm").orEmpty()
                        val sets = Array(5) { i -> intArrayOf(
                            ev.optString("Tr1S${i + 1}").toIntOrNull() ?: 0,
                            ev.optString("Tr2S${i + 1}").toIntOrNull() ?: 0
                        ) }
                        val winner = if (finished && p1.isNotEmpty() && p2.isNotEmpty()) {
                            val w1 = sets.count { it[0] > it[1] }; val w2 = sets.count { it[1] > it[0] }
                            if (w1 > w2) 1 else if (w2 > w1) 2 else null
                        } else null
                        tennis[eid] = TNev(eid, finished, status, winner, sets)
                    }
                }
            }
        } catch (e: Exception) {}

        // Tennis notifications are paused; keep the result lookup above so existing
        // tennis ticket legs can still settle without losing the user's records.

        // Ticket settlement: a leg settles when its match is finished (or void).
        val settledNow = mutableListOf<Pair<JSONObject, Boolean>>()
        val stillOpen = JSONArray()
        for (t in 0 until tickets.length()) {
            val ticket = tickets.getJSONObject(t)
            val legs = ticket.optJSONArray("legs")
            if (legs == null) { stillOpen.put(ticket); continue }
            val outcomes = mutableListOf<Boolean?>()
            for (i in 0 until legs.length()) {
                val leg = legs.getJSONObject(i)
                val eid = leg.optString("eid")
                val soccerEv = if (leg.optString("sport") != "tennis") soccer[eid] else null
                val tEv = if (leg.optString("sport") == "tennis") tennis[eid] else null
                val archived = archiveById[leg.optString("fixture")] ?: if (eid !in ambiguousEids) archiveByEid[eid] else null
                val matching = leg.optString("sport") != "tennis" && archived != null && archived.optString("home").equals(leg.optString("home"), true) &&
                    archived.optString("away").equals(leg.optString("away"), true) &&
                    (eid.isEmpty() || archived.optString("livescore_id") == eid) &&
                    (leg.optString("fixture").isEmpty() || archived.optString("id") == leg.optString("fixture"))
                val sc = if (matching) archived?.optJSONObject("score") else null
                fun stat(key: String): Int? {
                    val value = sc?.opt(key)
                    return if (value is Number && value.toDouble() == value.toInt().toDouble() && value.toInt() >= 0) value.toInt() else null
                }
                val hg = stat("hg"); val ag = stat("ag")
                val scope = listOf(archived?.optString("country"), archived?.optString("league"), archived?.optString("div")).joinToString(" ")
                val ambiguousCompetition = Regex("(?i)uefa|europe|champions league|europa league|conference league|\\bcup\\b").containsMatchIn(scope)
                val liveRegulation = soccerEv?.status == "FT" && soccerEv.hg == hg && soccerEv.ag == ag
                val competitionKnown = !archived?.optString("country").isNullOrBlank() && !archived?.optString("league").isNullOrBlank()
                val safeArchive = sc?.optString("status") == "FT" && hg != null && ag != null && competitionKnown &&
                    (!ambiguousCompetition || sc.optBoolean("regulation_confirmed") || liveRegulation)
                val result = when {
                    tEv != null && tEv.finished -> settleTennis(leg, tEv)
                    safeArchive -> TicketGrading.soccer(leg.optString("sel"), hg!!, ag!!, stat("hc"), stat("ac"))
                    soccerEv != null && soccerEv.status == "FT" && soccerEv.hg != null && soccerEv.ag != null ->
                        TicketGrading.soccer(leg.optString("sel"), soccerEv.hg, soccerEv.ag)
                    else -> null
                }
                outcomes.add(result)
            }
            val outcome = TicketGrading.ticket(outcomes)
            if (outcome != null) {
                settledNow.add(ticket to outcome)
            } else {
                stillOpen.put(ticket)
            }
        }
        for ((ticket, won) in settledNow) {
            val label = ticket.optString("label").ifEmpty { ticket.optString("title") }
            val legs = ticket.optJSONArray("legs")
            val lines = if (legs != null) (0 until legs.length()).joinToString("\n") {
                val leg = legs.getJSONObject(it)
                "${leg.optString("home").ifEmpty { leg.optString("p1") }} v ${leg.optString("away").ifEmpty { leg.optString("p2")}}" +
                        " — " + leg.optString("sel").ifEmpty { leg.optString("selection") }
            } else ""
            Notifier.notify(ctx, Notifier.CH_TICKETS, (label.hashCode() and 4095) + 4000,
                if (won) "🎉 Ticket won — $label" else "❌ Ticket lost — $label",
                lines, "bets")
        }
        if (settledNow.isNotEmpty()) {
            prefs.edit().putString("str_tickets", stillOpen.toString()).apply()
        }
    }

    /** Tennis leg settlement. Leg = {market, selection, line}; void on retirement/walkover. */
    private fun settleTennis(leg: JSONObject, ev: TNev): Boolean? {
        val line = leg.optDouble("line", Double.NaN).let { if (it.isNaN()) null else it }
        val retired = ev.status.startsWith("ret", true) || ev.status.startsWith("w.", true)
        return TicketGrading.tennis(leg.optString("market"), leg.optString("selection"), line, ev.winner,
            ev.sets.sumOf { it[0] }, ev.sets.sumOf { it[1] }, retired)
    }

    /** Latest goal scorer for the notification ("S. Player · "). Best-effort. */
    private fun latestScorer(eid: String): String {
        return try {
            val response = Net.get("https://prod-public-api.livescore.com/v1/api/app/incidents/soccer/$eid")
            if (response.code != 200) return ""
            val incs = JSONObject(response.body).optJSONObject("Incs") ?: return ""
            var latest: JSONObject? = null
            for (key in incs.keys()) {
                val arr = incs.optJSONArray(key) ?: continue
                for (i in 0 until arr.length()) {
                    val inc = arr.getJSONObject(i)
                    val candidates = mutableListOf(inc)
                    inc.optJSONArray("Incs")?.let { nested -> for (j in 0 until nested.length()) candidates.add(nested.getJSONObject(j)) }
                    for (c in candidates) {
                        if (c.optInt("IT") in setOf(36, 37, 39)) latest = c
                    }
                }
            }
            val l = latest ?: return ""
            val name = l.optString("Pn")
            if (name.isNotEmpty()) "$name " else
            listOf(l.optString("Fn"), l.optString("Ln")).filter { it.isNotEmpty() }.joinToString(" ")
        } catch (e: Exception) {
            ""
        }
    }
}
