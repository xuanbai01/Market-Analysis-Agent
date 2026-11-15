/** A real OptionsReport (NVDA, 2026-11-13 close), built by the backend from live
 * Yahoo data and trimmed; 70 synthetic history sessions so the percentile
 * shows. The schema test parses it, so the backend's shape is the contract. */
export const RAW_OPTIONS_REPORT = {
  "symbol": "NVDA",
  "name": "NVIDIA Corporation",
  "status": "ok",
  "spot": 162.85,
  "quoted_at": "2026-11-13T16:00:00-05:00",
  "at_close": true,
  "rate": 0.04122000217437744,
  "rate_assumed": false,
  "iv30": 0.5945863011548973,
  "iv30_extrapolated": false,
  "iv90": 0.5011597037537019,
  "skew25": 0.026943617471096415,
  "rv20": 0.5695120274722246,
  "rv60": 0.44089729442926656,
  "put_call_open_interest": 0.8576543213010227,
  "put_call_volume": 0.670639541251784,
  "expiries": [
    {
      "expiry": "2026-11-16",
      "days": 2.9999999999999996,
      "sessions": 1,
      "forward": 162.7384681495626,
      "forward_from_parity": true,
      "atm_iv": 0.4933452494789372,
      "expected_move": 0.044726523819927394,
      "low": 155.62011832503669,
      "high": 170.1824243594949,
      "straddle": 10.54,
      "straddle_strike": 172.5,
      "call_open_interest": 175164,
      "put_open_interest": 121003,
      "call_volume": 598880,
      "put_volume": 459964,
      "includes_earnings": false
    },
    {
      "expiry": "2026-11-18",
      "days": 5.0,
      "sessions": 3,
      "forward": 162.7765673672114,
      "forward_from_parity": true,
      "atm_iv": 0.9205535674777722,
      "expected_move": 0.10774264559308903,
      "low": 146.15034651732665,
      "high": 181.29420501039382,
      "straddle": 14.049999999999999,
      "straddle_strike": 162.5,
      "call_open_interest": 130579,
      "put_open_interest": 87290,
      "call_volume": 140365,
      "put_volume": 116064,
      "includes_earnings": true
    },
    {
      "expiry": "2026-11-20",
      "days": 7.0,
      "sessions": 5,
      "forward": 162.90031633325336,
      "forward_from_parity": true,
      "atm_iv": 0.874305460703466,
      "expected_move": 0.12107815058381954,
      "low": 144.32393285933068,
      "high": 183.86772405473843,
      "straddle": 15.700000000000001,
      "straddle_strike": 162.5,
      "call_open_interest": 1270948,
      "put_open_interest": 841857,
      "call_volume": 377579,
      "put_volume": 286524,
      "includes_earnings": true
    },
    {
      "expiry": "2026-11-27",
      "days": 14.0,
      "sessions": 9,
      "forward": 163.0508702604261,
      "forward_from_parity": true,
      "atm_iv": 0.7023266388032204,
      "expected_move": 0.13754877497068618,
      "low": 142.09750325830782,
      "high": 187.09397197749823,
      "straddle": 17.849999999999998,
      "straddle_strike": 162.5,
      "call_open_interest": 168164,
      "put_open_interest": 135718,
      "call_volume": 54503,
      "put_volume": 47758,
      "includes_earnings": true
    },
    {
      "expiry": "2026-12-11",
      "days": 28.0,
      "sessions": 19,
      "forward": 163.03458043821934,
      "forward_from_parity": true,
      "atm_iv": 0.60380452182394,
      "expected_move": 0.1672356815837976,
      "low": 137.92728784875132,
      "high": 192.7122241960828,
      "straddle": 21.849999999999998,
      "straddle_strike": 165.0,
      "call_open_interest": 58031,
      "put_open_interest": 42713,
      "call_volume": 22794,
      "put_volume": 11132,
      "includes_earnings": true
    },
    {
      "expiry": "2026-12-18",
      "days": 35.0,
      "sessions": 24,
      "forward": 163.17173264955204,
      "forward_from_parity": true,
      "atm_iv": 0.5757072236937044,
      "expected_move": 0.17827451710935155,
      "low": 136.52786099001628,
      "high": 195.01524555346154,
      "straddle": 23.125,
      "straddle_strike": 164.0,
      "call_open_interest": 1745177,
      "put_open_interest": 1586487,
      "call_volume": 166336,
      "put_volume": 114568,
      "includes_earnings": true
    },
    {
      "expiry": "2026-12-31",
      "days": 47.99999999999999,
      "sessions": 32,
      "forward": 163.51494146836976,
      "forward_from_parity": true,
      "atm_iv": 0.5425383117759079,
      "expected_move": 0.19674540497144763,
      "low": 134.3111289336363,
      "high": 199.06865719679357,
      "straddle": 25.375,
      "straddle_strike": 165.0,
      "call_open_interest": 10268,
      "put_open_interest": 7017,
      "call_volume": 12082,
      "put_volume": 8148,
      "includes_earnings": true
    },
    {
      "expiry": "2027-01-15",
      "days": 63.00000000000001,
      "sessions": 42,
      "forward": 163.76625343285778,
      "forward_from_parity": true,
      "atm_iv": 0.5258975215170392,
      "expected_move": 0.21848668056127055,
      "low": 131.6245361779412,
      "high": 203.75673519698705,
      "straddle": 28.375,
      "straddle_strike": 165.0,
      "call_open_interest": 1846262,
      "put_open_interest": 1617287,
      "call_volume": 219447,
      "put_volume": 74662,
      "includes_earnings": true
    },
    {
      "expiry": "2027-02-19",
      "days": 98.0,
      "sessions": 65,
      "forward": 164.51462649194363,
      "forward_from_parity": true,
      "atm_iv": 0.496307959508984,
      "expected_move": 0.25716854387977084,
      "low": 127.20894073303559,
      "high": 212.7606925568483,
      "straddle": 33.35,
      "straddle_strike": 165.0,
      "call_open_interest": 342031,
      "put_open_interest": 361669,
      "call_volume": 152011,
      "put_volume": 47797,
      "includes_earnings": true
    },
    {
      "expiry": "2027-05-21",
      "days": 189.0,
      "sessions": 129,
      "forward": 166.30250617371541,
      "forward_from_parity": true,
      "atm_iv": 0.47458627001573056,
      "expected_move": 0.34150702326529936,
      "low": 118.19093772230586,
      "high": 233.99868122409453,
      "straddle": 44.125,
      "straddle_strike": 165.0,
      "call_open_interest": 75500,
      "put_open_interest": 128798,
      "call_volume": 13277,
      "put_volume": 10615,
      "includes_earnings": true
    },
    {
      "expiry": "2027-12-17",
      "days": 399.0,
      "sessions": 274,
      "forward": 170.3972027590701,
      "forward_from_parity": true,
      "atm_iv": 0.46029170478563775,
      "expected_move": 0.4812526831643202,
      "low": 105.30696016230685,
      "high": 275.71973080757857,
      "straddle": 61.725,
      "straddle_strike": 170.0,
      "call_open_interest": 481348,
      "put_open_interest": 476361,
      "call_volume": 23049,
      "put_volume": 16723,
      "includes_earnings": true
    }
  ],
  "listed_expiries": [
    "2026-11-16",
    "2026-11-18",
    "2026-11-20",
    "2026-11-23",
    "2026-11-25",
    "2026-11-27",
    "2026-12-04",
    "2026-12-11",
    "2026-12-18",
    "2026-12-24",
    "2026-12-31",
    "2027-01-15",
    "2027-02-19",
    "2027-03-19",
    "2027-04-16",
    "2027-05-21",
    "2027-06-17",
    "2027-09-17",
    "2027-12-17",
    "2028-01-21",
    "2028-06-16",
    "2028-09-15",
    "2028-12-15",
    "2029-01-19"
  ],
  "chain": {
    "expiry": "2026-12-11",
    "days": 28.0,
    "forward": 163.03458043821934,
    "atm_iv": 0.60380452182394,
    "smile": [
      {
        "strike": 110.0,
        "log_moneyness": -0.3934819624414584,
        "iv": 0.7858951008108219,
        "side": "put"
      },
      {
        "strike": 120.0,
        "log_moneyness": -0.3064705854518287,
        "iv": 0.7176186114796742,
        "side": "put"
      },
      {
        "strike": 130.0,
        "log_moneyness": -0.22642787777829224,
        "iv": 0.666002489775873,
        "side": "put"
      },
      {
        "strike": 140.0,
        "log_moneyness": -0.15231990562457043,
        "iv": 0.6334122465121967,
        "side": "put"
      },
      {
        "strike": 150.0,
        "log_moneyness": -0.08332703413761891,
        "iv": 0.6129326529223916,
        "side": "put"
      },
      {
        "strike": 160.0,
        "log_moneyness": -0.018788513000047795,
        "iv": 0.603267059471745,
        "side": "put"
      },
      {
        "strike": 170.0,
        "log_moneyness": 0.041836108816386997,
        "iv": 0.5934447691183183,
        "side": "call"
      },
      {
        "strike": 185.0,
        "log_moneyness": 0.1263934968444501,
        "iv": 0.5895959484046028,
        "side": "call"
      },
      {
        "strike": 195.0,
        "log_moneyness": 0.1790372303298722,
        "iv": 0.5889758564134664,
        "side": "call"
      },
      {
        "strike": 215.0,
        "log_moneyness": 0.2766756998937881,
        "iv": 0.6166852148141401,
        "side": "call"
      },
      {
        "strike": 230.0,
        "log_moneyness": 0.3441169806893207,
        "iv": 0.6649552622261005,
        "side": "call"
      },
      {
        "strike": 245.0,
        "log_moneyness": 0.40729588231085234,
        "iv": 0.7219415711552049,
        "side": "call"
      }
    ],
    "rows": [
      {
        "strike": 135.0,
        "call_bid": 29.55,
        "call_ask": 30.7,
        "call_iv": 0.6669779681310694,
        "call_delta": 0.8730245057317051,
        "call_open_interest": 45,
        "call_volume": 5,
        "call_usable": true,
        "put_bid": 1.94,
        "put_ask": 2.06,
        "put_iv": 0.6481717541595235,
        "put_delta": -0.1269754942682949,
        "put_open_interest": 1270,
        "put_volume": 745,
        "put_usable": true
      },
      {
        "strike": 140.0,
        "call_bid": 25.4,
        "call_ask": 26.45,
        "call_iv": 0.6472090862230094,
        "call_delta": 0.8304521947738404,
        "call_open_interest": 51,
        "call_volume": 16,
        "call_usable": true,
        "put_bid": 2.74,
        "put_ask": 2.87,
        "put_iv": 0.6334122465121967,
        "put_delta": -0.16954780522615964,
        "put_open_interest": 2047,
        "put_volume": 1194,
        "put_usable": true
      },
      {
        "strike": 145.0,
        "call_bid": 21.6,
        "call_ask": 22.35,
        "call_iv": 0.6299328039060645,
        "call_delta": 0.7786808713370139,
        "call_open_interest": 130,
        "call_volume": 12,
        "call_usable": true,
        "put_bid": 3.8,
        "put_ask": 3.95,
        "put_iv": 0.6208141021018294,
        "put_delta": -0.2213191286629861,
        "put_open_interest": 2038,
        "put_volume": 883,
        "put_usable": true
      },
      {
        "strike": 150.0,
        "call_bid": 18.05,
        "call_ask": 18.6,
        "call_iv": 0.6150068085985807,
        "call_delta": 0.7175986742796046,
        "call_open_interest": 275,
        "call_volume": 154,
        "call_usable": true,
        "put_bid": 5.25,
        "put_ask": 5.35,
        "put_iv": 0.6129326529223916,
        "put_delta": -0.28240132572039545,
        "put_open_interest": 3912,
        "put_volume": 1019,
        "put_usable": true
      },
      {
        "strike": 155.0,
        "call_bid": 14.9,
        "call_ask": 15.35,
        "call_iv": 0.6085742033775228,
        "call_delta": 0.6496728692928134,
        "call_open_interest": 300,
        "call_volume": 169,
        "call_usable": true,
        "put_bid": 7.0,
        "put_ask": 7.2,
        "put_iv": 0.6076278088498175,
        "put_delta": -0.3503271307071866,
        "put_open_interest": 2068,
        "put_volume": 540,
        "put_usable": true
      },
      {
        "strike": 160.0,
        "call_bid": 12.15,
        "call_ask": 12.45,
        "call_iv": 0.603267059450546,
        "call_delta": 0.5776914012679304,
        "call_open_interest": 1092,
        "call_volume": 1893,
        "call_usable": true,
        "put_bid": 9.2,
        "put_ask": 9.35,
        "put_iv": 0.603267059471745,
        "put_delta": -0.4223085987320696,
        "put_open_interest": 3156,
        "put_volume": 1303,
        "put_usable": true
      },
      {
        "strike": 165.0,
        "call_bid": 9.85,
        "call_ask": 10.05,
        "call_iv": 0.6041473105085319,
        "call_delta": 0.5048078274410074,
        "call_open_interest": 2695,
        "call_volume": 2211,
        "call_usable": true,
        "put_bid": 11.7,
        "put_ask": 12.1,
        "put_iv": 0.6036341459713634,
        "put_delta": -0.4951921725589926,
        "put_open_interest": 3162,
        "put_volume": 621,
        "put_usable": true
      },
      {
        "strike": 170.0,
        "call_bid": 7.75,
        "call_ask": 7.75,
        "call_iv": 0.5934447691183183,
        "call_delta": 0.43158256975120535,
        "call_open_interest": 2386,
        "call_volume": 2502,
        "call_usable": true,
        "put_bid": 14.6,
        "put_ask": 15.05,
        "put_iv": 0.6008784698637709,
        "put_delta": -0.5684174302487947,
        "put_open_interest": 2382,
        "put_volume": 199,
        "put_usable": true
      },
      {
        "strike": 175.0,
        "call_bid": 6.0,
        "call_ask": 6.2,
        "call_iv": 0.5947593171610533,
        "call_delta": 0.36408104142791586,
        "call_open_interest": 4642,
        "call_volume": 1034,
        "call_usable": true,
        "put_bid": 17.8,
        "put_ask": 18.3,
        "put_iv": 0.5960815203225228,
        "put_delta": -0.6359189585720841,
        "put_open_interest": 2451,
        "put_volume": 106,
        "put_usable": true
      },
      {
        "strike": 180.0,
        "call_bid": 4.6,
        "call_ask": 4.8,
        "call_iv": 0.5929187822908674,
        "call_delta": 0.3012865871089021,
        "call_open_interest": 3569,
        "call_volume": 1254,
        "call_usable": true,
        "put_bid": 21.3,
        "put_ask": 22.1,
        "put_iv": 0.5985303237982867,
        "put_delta": -0.6987134128910979,
        "put_open_interest": 2426,
        "put_volume": 47,
        "put_usable": true
      },
      {
        "strike": 185.0,
        "call_bid": 3.45,
        "call_ask": 3.65,
        "call_iv": 0.5895959484046028,
        "call_delta": 0.24436068037551922,
        "call_open_interest": 8099,
        "call_volume": 727,
        "call_usable": true,
        "put_bid": 25.05,
        "put_ask": 25.9,
        "put_iv": 0.5916409802572642,
        "put_delta": -0.7556393196244808,
        "put_open_interest": 955,
        "put_volume": 57,
        "put_usable": true
      },
      {
        "strike": 190.0,
        "call_bid": 2.61,
        "call_ask": 2.74,
        "call_iv": 0.5891646040805403,
        "call_delta": 0.19588886882038248,
        "call_open_interest": 4641,
        "call_volume": 1496,
        "call_usable": true,
        "put_bid": 29.4,
        "put_ask": 30.0,
        "put_iv": 0.6006957627501703,
        "put_delta": -0.8041111311796175,
        "put_open_interest": 2540,
        "put_volume": 39,
        "put_usable": true
      }
    ],
    "open_interest": [
      {
        "strike": 100.0,
        "call": 15,
        "put": 2577
      },
      {
        "strike": 110.0,
        "call": 11,
        "put": 294
      },
      {
        "strike": 120.0,
        "call": 42,
        "put": 499
      },
      {
        "strike": 130.0,
        "call": 69,
        "put": 1653
      },
      {
        "strike": 140.0,
        "call": 51,
        "put": 2047
      },
      {
        "strike": 150.0,
        "call": 275,
        "put": 3912
      },
      {
        "strike": 160.0,
        "call": 1092,
        "put": 3156
      },
      {
        "strike": 170.0,
        "call": 2386,
        "put": 2382
      },
      {
        "strike": 180.0,
        "call": 3569,
        "put": 2426
      },
      {
        "strike": 190.0,
        "call": 4641,
        "put": 2540
      },
      {
        "strike": 200.0,
        "call": 6245,
        "put": 630
      },
      {
        "strike": 210.0,
        "call": 1890,
        "put": 238
      },
      {
        "strike": 220.0,
        "call": 3006,
        "put": 250
      },
      {
        "strike": 230.0,
        "call": 1511,
        "put": 60
      }
    ]
  },
  "earnings": {
    "next_date": "2026-11-17",
    "next_timing": "after_close",
    "estimated": false,
    "reaction_date": "2026-11-18",
    "implied_move": 0.07115450130555213,
    "implied_move_usd": 11.587510537609164,
    "event_sigma": 0.0891789424198827,
    "base_vol": 0.5541388709471804,
    "method": "two_after",
    "refused": null,
    "expiries": [
      "2026-11-18",
      "2026-11-27"
    ],
    "past": [
      {
        "announced": "2024-11-20",
        "timing": "after_close",
        "move": 0.0053323268227429,
        "spans_extra_day": false
      },
      {
        "announced": "2025-02-26",
        "timing": "after_close",
        "move": -0.08859150060287647,
        "spans_extra_day": false
      },
      {
        "announced": "2025-05-28",
        "timing": "after_close",
        "move": 0.03197357261352381,
        "spans_extra_day": false
      },
      {
        "announced": "2025-08-27",
        "timing": "after_close",
        "move": -0.007905597984344405,
        "spans_extra_day": false
      },
      {
        "announced": "2025-11-19",
        "timing": "after_close",
        "move": -0.032032318225409646,
        "spans_extra_day": false
      },
      {
        "announced": "2026-02-25",
        "timing": "after_close",
        "move": -0.05610613126070414,
        "spans_extra_day": false
      },
      {
        "announced": "2026-05-20",
        "timing": "after_close",
        "move": -0.01787940718646221,
        "spans_extra_day": false
      },
      {
        "announced": "2026-08-26",
        "timing": "after_close",
        "move": 0.08377069688720136,
        "spans_extra_day": false
      }
    ],
    "past_mean_abs": 0.04044894394790812
  },
  "history": {
    "points": [
      {
        "date": "2026-09-20",
        "iv30": 0.47
      },
      {
        "date": "2026-09-21",
        "iv30": 0.472
      },
      {
        "date": "2026-09-22",
        "iv30": 0.474
      },
      {
        "date": "2026-09-23",
        "iv30": 0.476
      },
      {
        "date": "2026-09-24",
        "iv30": 0.478
      },
      {
        "date": "2026-09-25",
        "iv30": 0.48
      },
      {
        "date": "2026-09-26",
        "iv30": 0.482
      },
      {
        "date": "2026-09-27",
        "iv30": 0.484
      },
      {
        "date": "2026-09-28",
        "iv30": 0.486
      },
      {
        "date": "2026-09-29",
        "iv30": 0.488
      },
      {
        "date": "2026-09-30",
        "iv30": 0.49
      },
      {
        "date": "2026-10-01",
        "iv30": 0.492
      },
      {
        "date": "2026-10-02",
        "iv30": 0.494
      },
      {
        "date": "2026-10-03",
        "iv30": 0.496
      },
      {
        "date": "2026-10-04",
        "iv30": 0.498
      },
      {
        "date": "2026-10-05",
        "iv30": 0.5
      },
      {
        "date": "2026-10-06",
        "iv30": 0.502
      },
      {
        "date": "2026-10-07",
        "iv30": 0.504
      },
      {
        "date": "2026-10-08",
        "iv30": 0.506
      },
      {
        "date": "2026-10-09",
        "iv30": 0.508
      }
    ],
    "sessions": 70,
    "since": "2026-08-01",
    "percentile": 100.0,
    "rank": null
  },
  "claims": [
    {
      "description": "Implied volatility, 30 days (IV30)",
      "value": 0.5945863011548973,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "total variance between the expiries around 30 days"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "Implied volatility, 90 days (IV90)",
      "value": 0.5011597037537019,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "total variance between the expiries around 90 days"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "Realized volatility, 20 sessions",
      "value": 0.5695120274722246,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "close-to-close, zero mean, \u00d7252"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "Realized volatility, 60 sessions",
      "value": 0.44089729442926656,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "close-to-close, zero mean, \u00d7252"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "IV30 minus realized volatility (20 sessions)",
      "value": 0.025074273682672676,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "IV30 \u2212 RV20"
      },
      "history": [],
      "unit": "percentage_points"
    },
    {
      "description": "25-delta skew, expiry nearest 30 days (put IV minus call IV)",
      "value": 0.026943617471096415,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "IV at the 25-delta put strike \u2212 IV at the 25-delta call strike"
      },
      "history": [],
      "unit": "percentage_points"
    },
    {
      "description": "Put/call open interest, expiries read",
      "value": 0.8576543213010227,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "\u03a3 put OI \u00f7 \u03a3 call OI"
      },
      "history": [],
      "unit": "ratio"
    },
    {
      "description": "Expected move to 2026-12-11 (one standard deviation)",
      "value": 0.1672356815837976,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "ATM IV \u00d7 \u221aT"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "Implied earnings move, report on 2026-11-17 (expected absolute move)",
      "value": 0.07115450130555213,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "\u221a(2/\u03c0) \u00d7 the report's \u03c3, from the expiries around it"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "Average absolute move after the last 8 reports",
      "value": 0.04044894394790812,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "mean |ln(close after \u00f7 close before)|"
      },
      "history": [],
      "unit": "fraction"
    },
    {
      "description": "IV30 percentile over 70 stored sessions",
      "value": 100.0,
      "source": {
        "tool": "computed.options",
        "fetched_at": "2026-11-15T05:37:50.470486Z",
        "url": null,
        "detail": "share of stored daily IV30s at or below today's"
      },
      "history": [],
      "unit": "percent"
    }
  ],
  "generated_at": "2026-11-15T05:37:50.470486Z"
} as const;

/** A symbol with no listed options, as the backend builds it (BRK-A). */
export const RAW_NO_OPTIONS_REPORT = {
  "symbol": "BRK-A",
  "name": null,
  "status": "no_options",
  "spot": null,
  "quoted_at": "2026-11-13T16:00:00-05:00",
  "at_close": true,
  "rate": 0.0372,
  "rate_assumed": false,
  "iv30": null,
  "iv30_extrapolated": false,
  "iv90": null,
  "skew25": null,
  "rv20": null,
  "rv60": null,
  "put_call_open_interest": null,
  "put_call_volume": null,
  "expiries": [],
  "listed_expiries": [],
  "chain": null,
  "earnings": null,
  "history": { "points": [], "sessions": 0, "since": null, "percentile": null, "rank": null },
  "claims": [],
  "generated_at": "2026-11-14T17:00:00Z"
} as const;
