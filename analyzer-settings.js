// Trade Analyzer settings. Change these numbers to tune how trades are graded.
window.ANALYZER_SETTINGS = {
  // Each team's grade score = own * (how much better its team got) + gap * (how it did vs. the other side)
  blend: { own: 0.75, gap: 0.25 },

  // Score of at least "big" = A (at most -big = F); at least "small" = B (at most -small = D); otherwise C
  gradeGaps: { big: 2000, small: 1000 },

  // How much to trust this league's trade history (1 = fully, 0 = ignore it and use market values only)
  leagueWeight: 1,

  // "Stud tax": higher means one great player beats several good ones by more.
  // 1 = straight sum. 1.25 means two equal players are worth about 1.74 of one.
  studPower: 1.25,

  // Boost or cut from this season's league-scored finish at his position
  production: [
    { upTo: 5, change: 0.10 },
    { upTo: 12, change: 0.05 },
    { upTo: 24, change: 0 },
    { upTo: 36, change: -0.05 },
    { upTo: 999, change: -0.10 }
  ],

  // Value cut for injury status
  injury: { Out: -0.08, IR: -0.08, PUP: -0.08, Sus: -0.05, Doubtful: -0.04 },

  // When a position's value shifts from long term toward win now: starts at "peak", fully by "cliff"
  ages: {
    QB: { peak: 26, cliff: 34 },
    RB: { peak: 23, cliff: 28 },
    WR: { peak: 24, cliff: 30 },
    TE: { peak: 25, cliff: 31 }
  },

  // How each team window weighs win-now value and long-term value
  window: {
    Contender: { now: 1.15, future: 0.75 },
    Middle: { now: 1, future: 1 },
    Rebuilder: { now: 0.5, future: 1.15 }
  }
};
