package com.playreport.app

import org.junit.Assert.*
import org.junit.Test

class TicketGradingTest {
    @Test fun soccerCodesUseTenthsAndHandleDraws() {
        assertEquals(true, TicketGrading.soccer("O15", 1, 1))
        assertEquals(false, TicketGrading.soccer("O25", 1, 1))
        assertEquals(true, TicketGrading.soccer("D", 1, 1))
        assertEquals(true, TicketGrading.soccer("1X", 1, 1))
        assertEquals(true, TicketGrading.soccer("HO05", 1, 0))
        assertNull(TicketGrading.soccer("CO95", 2, 1))
    }
    @Test fun openLegPreventsWinningNotification() {
        assertNull(TicketGrading.ticket(listOf(true, null)))
        assertNull(TicketGrading.ticket(emptyList()))
        assertEquals(true, TicketGrading.ticket(listOf(true, true)))
        assertEquals(false, TicketGrading.ticket(listOf(false, null)))
    }
    @Test fun tennisSelectionsMatchTheAppAndRetirementsAreConservative() {
        assertEquals(true, TicketGrading.tennis("winner", "player_a", null, 1, 12, 8, false))
        assertEquals(false, TicketGrading.tennis("winner", "player_b", null, 1, 12, 8, false))
        assertEquals(true, TicketGrading.tennis("total_games", "over", 19.5, 1, 12, 8, false))
        assertNull(TicketGrading.tennis("total_games", "over", 19.5, 1, 12, 8, true))
        assertNull(TicketGrading.tennis("winner", "player_a", null, 1, 12, 8, true))
        assertEquals(true, TicketGrading.tennis("game_handicap", "player_b", 4.5, 1, 12, 8, false))
    }
}
