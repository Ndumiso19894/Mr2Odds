package com.playreport.app

/** Pure settlement rules shared by the background checker; null means not safely decidable. */
internal object TicketGrading {
    fun ticket(results: List<Boolean?>): Boolean? = when {
        results.isEmpty() -> null
        results.any { it == false } -> false
        results.all { it == true } -> true
        else -> null
    }

    private fun line(raw: String): Double? {
        val n = raw.toDoubleOrNull() ?: return null
        // App market codes use tenths: O15 = over 1.5; older decimal codes are also supported.
        return if (raw.contains('.')) n else n / 10.0
    }

    fun soccer(sel: String, hg: Int, ag: Int, hc: Int? = null, ac: Int? = null): Boolean? {
        return when (sel) {
        "H" -> hg > ag
        "D", "X" -> hg == ag
        "A" -> ag > hg
        "1X", "HS" -> hg >= ag
        "12" -> hg != ag
        "X2", "AS" -> ag >= hg
        "BTTS" -> hg > 0 && ag > 0
        "NB", "NBTTS" -> !(hg > 0 && ag > 0)
        else -> {
            val total = Regex("^([OU])(\\d+(?:\\.\\d+)?)$").matchEntire(sel)
            val team = Regex("^([HA])([OU])(\\d+(?:\\.\\d+)?)$").matchEntire(sel)
            val corners = Regex("^C([HA])?([OU])(\\d+(?:\\.\\d+)?)$").matchEntire(sel)
            when {
                corners != null -> {
                    val n = line(corners.groupValues[3]) ?: return null
                    val count = when (corners.groupValues[1]) {
                        "H" -> hc
                        "A" -> ac
                        else -> if (hc != null && ac != null) hc + ac else null
                    } ?: return null
                    if (count < 0 || count.toDouble() == n) null
                    else if (corners.groupValues[2] == "O") count > n else count < n
                }
                total != null -> {
                    val n = line(total.groupValues[2]) ?: return null
                    val goals = (hg + ag).toDouble()
                    if (goals == n) null else if (total.groupValues[1] == "O") goals > n else goals < n
                }
                team != null -> {
                    val n = line(team.groupValues[3]) ?: return null
                    val goals = (if (team.groupValues[1] == "H") hg else ag).toDouble()
                    if (goals == n) null else if (team.groupValues[2] == "O") goals > n else goals < n
                }
                else -> null // corners/cards need final match statistics, not just the score
            }
        }
    }

    }

    fun tennis(market: String, selection: String, line: Double?, winner: Int?, p1: Int, p2: Int,
               retired: Boolean): Boolean? {
        val pick = selection.lowercase()
        // Set counts do not prove the winner after a retirement or walkover.
        if (retired) return null
        if (market == "winner") {
            val side = when (pick) { "player_a", "1", "p1" -> 1; "player_b", "2", "p2" -> 2; else -> return null }
            return winner?.let { it == side }
        }
        if (line == null) return null
        if (market == "game_handicap") {
            val delta = when (pick) { "player_a", "1", "p1" -> p1 + line - p2
                                     "player_b", "2", "p2" -> p2 + line - p1
                                     else -> return null }
            return if (delta == 0.0) null else delta > 0
        }
        val games = when (market) { "total_games" -> p1 + p2; "p1_games" -> p1; "p2_games" -> p2; else -> return null }
        if (games.toDouble() == line) return null
        return when (pick) { "over", "o" -> games > line; "under", "u" -> games < line; else -> null }
    }
}
