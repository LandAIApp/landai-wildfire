"""V7.6 temporal windows (getTimeWindows)."""
from __future__ import annotations

import ee


def get_time_windows(fire_date: ee.Date, analysis_end: ee.Date) -> dict[str, ee.Date]:
    """Return PRE/POST/HISTORY windows as ee.Dates; END values are exclusive.

    PRE      [fire - 90 d, fire - 7 d)
    POST     [fire, analysisEnd + 1 d)
    HISTORY  [fire - 6 months, fire - 15 d)
    """
    return {
        'PRE_START': fire_date.advance(-90, 'day'),
        'PRE_END': fire_date.advance(-7, 'day'),
        'POST_START': fire_date,
        'POST_END': analysis_end.advance(1, 'day'),
        'HISTORY_START': fire_date.advance(-6, 'month'),
        'HISTORY_END': fire_date.advance(-15, 'day'),
    }
