"""Every user-facing string, in both languages.

Two rules keep this honest:

  * Nothing in render.py or build.py prints a bare English sentence. If a
    string reaches a reader, it lives here, in both languages.
  * The Spanish is written for a Latin American baseball audience, not
    translated word-for-word from the English. A strikeout is a *ponche*,
    ERA is *efectividad*, innings pitched are *entradas lanzadas*, and a
    starting pitcher is an *abridor*. Rendering those as literal
    translations of the English terms would read as machine output to
    exactly the people this is for.

Dates are formatted from the tables below rather than via the C locale,
because a GitHub runner has no guarantee of having es_ES installed and a
silent fall back to English dates is the kind of half-translation that makes
a site look abandoned.
"""
from __future__ import annotations

# Only English is published. The Spanish column below is kept rather than
# deleted: every string already has a translation, so switching the site back
# to two languages is one entry in this tuple — but nothing renders it today,
# and a half-built /es/ tree is worse than none.
LANGS = ("en",)
ALL_LANGS = ("en", "es")

# The play card's argument, assembled from the structured reasons that
# find_plays stores. Same numbers, two languages.
REASONS = {
    "en": {
        "consensus": "Vig-free consensus across <b>{books} books</b> is {fair} ({pct} to win)",
        "best_price": "Best number on the board is <b>{price} at {book}</b>",
        "books_shorter": "<b>{shorter} of {books}</b> books price this shorter than we're getting it",
        "edge": "Expected value at that price: <b>+{edge}%</b> per unit risked",
        "consensus_number": "Consensus number is {point} — books off that number were excluded",
    },
    "es": {
        "consensus": "El consenso sin vigorish entre <b>{books} casas</b> es {fair} ({pct} de ganar)",
        "best_price": "El mejor número disponible es <b>{price} en {book}</b>",
        "books_shorter": "<b>{shorter} de {books}</b> casas lo pagan más corto de lo que lo estamos tomando",
        "edge": "Valor esperado a ese precio: <b>+{edge}%</b> por unidad arriesgada",
        "consensus_number": "El número de consenso es {point} — se excluyeron las casas fuera de ese número",
    },
}

MONTHS = {
    "en": ["January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"],
}
WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
}

T = {
    # ---- navigation and chrome
    "nav_plays":    {"en": "Today's Plays",  "es": "Jugadas de hoy"},
    "nav_tonight":  {"en": "Tonight",        "es": "Esta noche"},
    "nav_board":    {"en": "Board",          "es": "Pizarra"},
    "nav_pitchers": {"en": "Pitchers Prop",  "es": "Props de lanzadores"},
    "nav_record":   {"en": "Track Record",   "es": "Historial"},
    "nav_about":    {"en": "How It Works",   "es": "Cómo funciona"},
    "nav_screens":  {"en": "The Screens",    "es": "Los filtros"},
    "nav_why":      {"en": "Why it's free",  "es": "Por qué es gratis"},
    "cta_plays":    {"en": "Today's plays",  "es": "Jugadas de hoy"},
    "lang_other":   {"en": "Español",        "es": "English"},

    # ---- status strip
    "sb_live":      {"en": "Board live",     "es": "Pizarra activa"},
    "sb_noboard":   {"en": "No board yet",   "es": "Sin pizarra aún"},
    "sb_rated":     {"en": "{n} game{s} rated", "es": "{n} juego{s} evaluado{s}"},
    "sb_flagged":   {"en": "{n} flagged",    "es": "{n} marcado{s}"},
    "sb_median":    {"en": "Median disagreement {v}", "es": "Discrepancia mediana {v}"},
    "sb_updated":   {"en": "Updated {v} ET", "es": "Actualizado {v} ET"},
    "pts":          {"en": "pts",            "es": "pts"},

    # ---- the board card
    "winprob":      {"en": "{team} win prob", "es": "Prob. victoria {team}"},
    "market":       {"en": "market",          "es": "mercado"},
    "vs_market":    {"en": "{v} pts vs market", "es": "{v} pts vs mercado"},
    "off_market":   {"en": "{v} pts off market", "es": "{v} pts fuera del mercado"},
    "agree_market": {"en": "in line with the market",
                     "es": "en línea con el mercado"},
    "market_na":    {"en": "market n/a",      "es": "sin mercado"},
    "final":        {"en": "Final {v}",       "es": "Final {v}"},
    "scheduled":    {"en": "Scheduled",       "es": "Programado"},
    "tbd":          {"en": "TBD",             "es": "Por definir"},
    "starts":       {"en": "{n} start{s}",    "es": "{n} apertura{s}"},
    "thin_sample":  {"en": "thin sample",     "es": "muestra escasa"},
    "era":          {"en": "ERA",             "es": "EFE"},
    "ip":           {"en": "IP",              "es": "EL"},
    "flagnote": {
        "en": "&#9888; Flagged as our error — {v} pts of disagreement is a bug, "
              "not an opportunity. Not eligible to become a play.",
        "es": "&#9888; Marcado como error nuestro — {v} pts de discrepancia es un "
              "fallo, no una oportunidad. No puede convertirse en jugada.",
    },
    "at_home":     {"en": "at home",     "es": "en casa"},
    "on_the_road": {"en": "on the road", "es": "de visita"},
    "rec_line":    {"en": "{wl} &middot; {split} {venue}",
                    "es": "{wl} &middot; {split} {venue}"},
    "market_tick": {"en": "Where the market has it",
                    "es": "Dónde lo tiene el mercado"},
    "market_fav":  {"en": "Market {pct} {team}", "es": "Mercado {pct} {team}"},
    "lean_on":     {"en": "{v} on {team}",       "es": "{v} en {team}"},
    "empty_board": {
        "en": "No games rated today. The board fills in every morning there's a slate.",
        "es": "Hoy no hay juegos evaluados. La pizarra se llena cada mañana que haya cartelera.",
    },

    # Market names. Baseball calls a spread a run line; nothing else does.
    # These are keys rather than literals so the renderer never has to know
    # which sport it is drawing.
    "mkt_moneyline": {"en": "Moneyline",  "es": "Línea de dinero"},
    "mkt_spread":    {"en": "Spread",     "es": "Hándicap"},
    "mkt_run_line":  {"en": "Run line",   "es": "Línea de carreras"},
    "mkt_total":     {"en": "Total",      "es": "Total"},
    "market_only":   {"en": "market only", "es": "solo mercado"},
    "board_empty":   {"en": "No games on the board tonight.",
                      "es": "No hay partidos en el tablero esta noche."},
    "card_more":     {"en": "Form, head to head and props",
                      "es": "Forma, historial y props"},

    # ---- board card detail panel
    "pnl_form":      {"en": "Form", "es": "Forma"},
    "pnl_record":    {"en": "Record", "es": "Récord"},
    "pnl_last10":    {"en": "Last 10", "es": "Últimos 10"},
    "pnl_streak":    {"en": "Streak", "es": "Racha"},
    "pnl_won_n":     {"en": "won {n} in a row", "es": "{n} victorias seguidas"},
    "pnl_lost_n":    {"en": "lost {n} in a row", "es": "{n} derrotas seguidas"},
    "pnl_won_last":  {"en": "won its last", "es": "ganó el último"},
    "pnl_lost_last": {"en": "lost its last", "es": "perdió el último"},
    "pnl_h2h":       {"en": "Head to head", "es": "Historial"},
    "pnl_h2h_none":  {"en": "They have not met yet this season.",
                      "es": "Aún no se han enfrentado esta temporada."},
    "pnl_h2h_lead":  {"en": "{team} lead the season series <b>{w}&ndash;{l}</b>",
                      "es": "{team} domina la serie <b>{w}&ndash;{l}</b>"},
    "pnl_h2h_even":  {"en": "The season series is level at <b>{w}&ndash;{l}</b>",
                      "es": "La serie está empatada <b>{w}&ndash;{l}</b>"},
    "pnl_h2h_more":  {"en": "{n} earlier meeting{s} not shown",
                      "es": "{n} enfrentamiento{s} anterior{s} no mostrado{s}"},
    "pnl_h2h_at":    {"en": "at {place}", "es": "en {place}"},
    "pnl_starters":  {"en": "Tonight&rsquo;s starters", "es": "Abridores de hoy"},
    "pnl_vs_line":   {"en": "{n} start{s} against the {team}: {ip} innings, "
                            "{k} strikeouts ({k9} per nine), {era} ERA",
                      "es": "{n} apertura{s} ante {team}: {ip} entradas, "
                            "{k} ponches ({k9} por nueve), efectividad {era}"},
    "pnl_vs_never":  {"en": "has not faced the {team} in {span}",
                      "es": "no ha enfrentado a {team} en {span}"},
    "pnl_props":     {"en": "Tonight&rsquo;s strikeout props",
                      "es": "Props de ponches de hoy"},
    "pnl_prop_line": {"en": "strikeouts &middot; ours <b>{ours}</b> &middot; "
                            "line <b>{line}</b> &middot; {prices}",
                      "es": "ponches &middot; nuestro <b>{ours}</b> &middot; "
                            "línea <b>{line}</b> &middot; {prices}"},

    # ---- the matchup verdict, shared by both panels
    "mx_favourable": {"en": "favourable matchup", "es": "duelo favorable"},
    "mx_tough":      {"en": "tough matchup", "es": "duelo difícil"},
    "mx_neutral":    {"en": "ordinary matchup", "es": "duelo normal"},

    # ---- prop card matchup panel
    "mx_open":       {"en": "matchup detail", "es": "detalle del duelo"},
    "mx_hist":       {"en": "{who} against {team}, {span}",
                      "es": "{who} ante {team}, {span}"},
    "mx_never":      {"en": "{who} has never faced {team}",
                      "es": "{who} nunca ha enfrentado a {team}"},
    "mx_never_v":    {"en": "No starts against them in 2025 or 2026, so there "
                            "is nothing here to read. The projection does not "
                            "use this line either way &mdash; it is context, "
                            "not an input.",
                      "es": "Sin aperturas ante ellos en 2025 ni 2026, así que "
                            "aquí no hay nada que leer. La proyección no usa "
                            "esta línea de todos modos &mdash; es contexto, no "
                            "un insumo."},
    "mx_starts":     {"en": "starts", "es": "aperturas"},
    "mx_innings":    {"en": "innings", "es": "entradas"},
    "mx_k":          {"en": "K", "es": "P"},
    "mx_k9":         {"en": "K per 9", "es": "P por 9"},
    "mx_era":        {"en": "ERA", "es": "EFE"},
    "mx_read":       {"en": "{k9} per nine against them, against {season} all "
                            "season.",
                      "es": "{k9} por nueve ante ellos, contra {season} en la "
                            "temporada."},
    "mx_thin":       {"en": "{n} start{s} is not evidence. It is shown because "
                            "it is the kind of thing you want to see, not "
                            "because it moves the number.",
                      "es": "{n} apertura{s} no es evidencia. Se muestra porque "
                            "es lo que uno quiere ver, no porque mueva el "
                            "número."},
    "mx_how":        {"en": "How {team} strike out",
                      "es": "Cómo se poncha {team}"},
    "mx_vs_r":       {"en": "vs right-handers", "es": "ante derechos"},
    "mx_vs_l":       {"en": "vs left-handers", "es": "ante zurdos"},
    # The table row label and the sentence noun are not the same string:
    # "and 24th against vs right-handers" is what sharing one produces.
    "mx_righties":   {"en": "right-handers", "es": "los derechos"},
    "mx_lefties":    {"en": "left-handers", "es": "los zurdos"},
    "mx_league":     {"en": "league average", "es": "promedio de la liga"},
    "mx_pa":         {"en": "{n} PA", "es": "{n} AP"},
    "mx_applies":    {"en": "{who} throws {hand}, so this is the rate that "
                            "applies to him. {team} rank {overall} against "
                            "everybody",
                      "es": "{who} lanza con la {hand}, así que esta es la tasa "
                            "que aplica. {team} es {overall} ante todos"},
    "mx_and_hand":   {"en": " and {split} against {hand_word}.",
                      "es": " y {split} ante {hand_word}."},
    "mx_same":       {"en": ", the same as against {hand_word} alone.",
                      "es": ", igual que solo ante {hand_word}."},
    "mx_right":      {"en": "right", "es": "derecha"},
    "mx_left":       {"en": "left", "es": "zurda"},
    "mx_delta":      {"en": "{v} points vs league", "es": "{v} puntos vs la liga"},
    "best_at":       {"en": "best at {book}", "es": "mejor en {book}"},
    "fair_is":       {"en": "fair {price}",   "es": "justo {price}"},
    "n_books":       {"en": "{n} books",      "es": "{n} casas"},
    "board_eyebrow": {"en": "{d} · {n} games priced",
                      "es": "{d} · {n} partidos con precio"},

    # ---- play cards
    "posted":       {"en": "Posted {v}",      "es": "Publicada {v}"},
    "play_n_of":    {"en": "Play {i} of {n}", "es": "Jugada {i} de {n}"},
    "stake":        {"en": "Stake",           "es": "Riesgo"},
    "edge_vs_fair": {"en": "Edge vs fair",    "es": "Ventaja vs justo"},
    "fair_price":   {"en": "Fair price",      "es": "Precio justo"},
    "no_plays_t":   {"en": "No plays today",  "es": "Hoy no hay jugadas"},
    "no_plays_h":   {"en": "No qualifying plays", "es": "Ninguna jugada calificó"},
    "no_plays_sub": {"en": "Checked every game on the board",
                     "es": "Se revisó cada juego de la pizarra"},
    "no_plays_body": {
        "en": "Nothing on the board cleared the edge threshold this morning. A card "
              "with no plays is a normal outcome — forcing one is how a good process "
              "turns into a bad month.",
        "es": "Nada en la pizarra superó el umbral de ventaja esta mañana. Un día sin "
              "jugadas es un resultado normal — forzar una es como un buen proceso se "
              "convierte en un mal mes.",
    },
    "all_plays":    {"en": "All plays",       "es": "Todas las jugadas"},

    # ---- tables
    "th_date":   {"en": "Date",   "es": "Fecha"},
    "th_pick":   {"en": "Pick",   "es": "Selección"},
    "th_league": {"en": "League", "es": "Liga"},
    "th_price":  {"en": "Price",  "es": "Precio"},
    "th_edge":   {"en": "Edge",   "es": "Ventaja"},
    "th_clv":    {"en": "CLV",    "es": "CLV"},
    "th_result": {"en": "Result", "es": "Resultado"},
    "th_pl":     {"en": "P/L",    "es": "G/P"},
    "res_win":   {"en": "Win",    "es": "Ganada"},
    "res_loss":  {"en": "Loss",   "es": "Perdida"},
    "res_push":  {"en": "Push",   "es": "Empate"},
    "res_pending": {"en": "Pending", "es": "Pendiente"},
    "no_graded": {
        "en": "No graded plays yet — the first results land the morning after the first card.",
        "es": "Aún no hay jugadas calificadas — los primeros resultados llegan la mañana "
              "siguiente a la primera cartelera.",
    },
    "nothing_yesterday": {"en": "Nothing graded from yesterday yet.",
                          "es": "Aún no hay nada calificado de ayer."},

    # ---- calibration
    "cal_said":    {"en": "We said",       "es": "Dijimos"},
    "cal_games":   {"en": "{n} games",     "es": "{n} juegos"},
    "within_noise": {"en": "within noise", "es": "dentro del ruido"},
    "too_low":     {"en": "we were too low",  "es": "nos quedamos cortos"},
    "too_high":    {"en": "we were too high", "es": "nos pasamos"},
    "cal_empty":   {"en": "Nothing graded yet — this fills in as rated games finish.",
                    "es": "Aún no hay nada calificado — esto se llena conforme terminen "
                          "los juegos evaluados."},
    "said_won":    {"en": "said {a} · won {b}", "es": "dijimos {a} · ganaron {b}"},

    # ---- pitcher board
    "our_projection": {"en": "Our projection", "es": "Nuestra proyección"},
    "posted_line":    {"en": "Posted line",    "es": "Línea publicada"},
    "last_n_starts":  {"en": "Last {n} starts", "es": "Últimas {n} aperturas"},
    "over_line":      {"en": "over {v}",       "es": "sobre {v}"},
    "in_line":        {"en": "in line",        "es": "en línea"},
    "over_the_line":  {"en": "{v} over the line",  "es": "{v} sobre la línea"},
    "under_the_line": {"en": "{v} under the line", "es": "{v} bajo la línea"},
    "off_the_line":   {"en": "&#9888; {v} off the line",
                       "es": "&#9888; {v} fuera de la línea"},
    "rated":          {"en": "Rated",          "es": "Evaluada"},
    "final_k":        {"en": "Final {n} K · {side}", "es": "Final {n} P · {side}"},
    "over":           {"en": "over",           "es": "sobre"},
    "under":          {"en": "under",          "es": "bajo"},
    "season":         {"en": "Season",         "es": "Temporada"},
    "opp_ks":         {"en": "{team} strikeouts", "es": "Ponches de {team}"},
    "per_game":       {"en": "{v} per game",   "es": "{v} por juego"},
    "never_faced":    {"en": "vs {team} · never faced them",
                       "es": "vs {team} · nunca los ha enfrentado"},
    "pitch_empty":    {"en": "No starter had a posted strikeout line today. This board "
                             "fills in whenever prop odds are available.",
                       "es": "Hoy ningún abridor tuvo línea de ponches publicada. Esta "
                             "pizarra se llena cuando hay cuotas de props disponibles."},
    "coin_flip":      {"en": "a coin flip",    "es": "un volado"},
    "better_coin":    {"en": "better than a coin flip", "es": "mejor que un volado"},
    "worse_coin":     {"en": "worse than a coin flip",  "es": "peor que un volado"},
    "pct_right":      {"en": "{v}% right",     "es": "{v}% acertado"},
    "n_starts":       {"en": "{n} start{s}",   "es": "{n} apertura{s}"},

    # ---- footer
    "foot_tagline": {
        "en": "Free plays, posted daily, graded in public. No packages, no premium tier, no DMs.",
        "es": "Jugadas gratis, publicadas a diario, calificadas en público. Sin paquetes, "
              "sin nivel premium, sin mensajes privados.",
    },
    "foot_plays":  {"en": "Plays",        "es": "Jugadas"},
    "foot_trans":  {"en": "Transparency", "es": "Transparencia"},
    "foot_about":  {"en": "About",        "es": "Acerca de"},
    "foot_today":  {"en": "Today's board",      "es": "Pizarra de hoy"},
    "foot_yest":   {"en": "Yesterday's results", "es": "Resultados de ayer"},
    "foot_log":    {"en": "Full play log",      "es": "Registro completo"},
    "foot_method": {"en": "Methodology",        "es": "Metodología"},
    "foot_resp":   {"en": "Play responsibly",   "es": "Juega con responsabilidad"},
    "foot_faq":    {"en": "FAQ",                "es": "Preguntas frecuentes"},
    "disclaimer": {
        "en": "<b>21+ only. For entertainment purposes.</b> Craftypicks is not a "
              "sportsbook and does not accept wagers, hold funds, or facilitate betting "
              "of any kind. Nothing here is financial advice or a guarantee of profit — "
              "every play posted can lose, and most winning stretches are followed by "
              "losing ones. Never wager money you cannot afford to lose. If gambling "
              "stops being fun, call <b>1-800-GAMBLER</b> or text 800GAM to 800177.",
        "es": "<b>Solo para mayores de 21 años. Con fines de entretenimiento.</b> "
              "Craftypicks no es una casa de apuestas: no acepta apuestas, no retiene "
              "fondos ni facilita ningún tipo de juego. Nada de lo aquí publicado es "
              "asesoría financiera ni una garantía de ganancia — toda jugada publicada "
              "puede perder, y a la mayoría de las rachas ganadoras le siguen rachas "
              "perdedoras. Nunca apuestes dinero que no puedas permitirte perder. Si el "
              "juego deja de ser divertido, llama al <b>1-800-GAMBLER</b> o envía 800GAM "
              "al 800177.",
    },
    "foot_copy": {
        "en": "&copy; {year} Craftypicks. Plays are posted before the number moves and "
              "graded exactly as posted.",
        "es": "&copy; {year} Craftypicks. Las jugadas se publican antes de que se mueva "
              "el número y se califican exactamente como se publicaron.",
    },
    "fineprint": {"en": "21+ &middot; Entertainment only &middot; Nothing here is for sale",
                  "es": "21+ &middot; Solo entretenimiento &middot; Aquí no se vende nada"},
    "sample_data": {
        "en": "<b>Sample data.</b> These plays were generated for testing — no real odds "
              "feed is connected yet. Add your ODDS_API_KEY and run the daily job to "
              "replace them.",
        "es": "<b>Datos de prueba.</b> Estas jugadas se generaron para pruebas — todavía "
              "no hay una fuente de cuotas real conectada. Agrega tu ODDS_API_KEY y "
              "ejecuta el trabajo diario para reemplazarlas.",
    },
    "not_rated": {"en": "Not yet rated", "es": "Aún sin evaluar"},

    # ---- KPI strips
    "kpi_units":      {"en": "Units won",     "es": "Unidades ganadas"},
    "kpi_units_sub":  {"en": "Flat 1u stake on every play",
                       "es": "Riesgo fijo de 1u en cada jugada"},
    "kpi_roi":        {"en": "ROI",           "es": "ROI"},
    "kpi_roi_home":   {"en": "Across {n} graded plays",
                       "es": "Sobre {n} jugadas calificadas"},
    "kpi_roi_rec":    {"en": "Return on {v}u risked",
                       "es": "Retorno sobre {v}u arriesgadas"},
    "kpi_record":     {"en": "Record",        "es": "Récord"},
    "kpi_record_sub": {"en": "{v}% on decided plays",
                       "es": "{v}% en jugadas decididas"},
    "kpi_losing":     {"en": "Losing months", "es": "Meses perdedores"},
    "kpi_losing_sub": {"en": "We post those too", "es": "Esos también los publicamos"},
    "kpi_clv":        {"en": "Beat the close", "es": "Le gana al cierre"},
    "kpi_clv_sub":    {"en": "On {n} plays with a late line",
                       "es": "En {n} jugadas con línea tardía"},

    # ---- the evidence block: profit vs the closing line
    "kpi_clv_sigma": {"en": "{v}\u03c3 from chance on {n} plays",
                      "es": "{v}\u03c3 del azar en {n} jugadas"},
    "kpi_roi_range": {"en": "consistent with {lo} to {hi}",
                      "es": "compatible con {lo} a {hi}"},
    "ev_by_profit":  {"en": "Graded on profit", "es": "Calificadas por ganancia"},
    "ev_by_close":   {"en": "Measured against the close",
                      "es": "Medidas contra el cierre"},
    "ev_profit_none": {
        "en": "Nothing is graded yet. When it is, this column will still be the "
              "slower of the two — a win rate needs thousands of plays before it "
              "separates a real edge from a warm streak.",
        "es": "Aún no hay nada calificado. Cuando lo haya, esta columna seguirá "
              "siendo la más lenta de las dos.",
    },
    "ev_profit_thin": {
        "en": "{n} graded. Far too few to compute anything honest about — a "
              "record this short is consistent with almost any true edge, "
              "including none.",
        "es": "{n} calificadas. Muy pocas para calcular nada honesto.",
    },
    "ev_profit_losing": {
        "en": "{n} graded, and currently losing. There is no sample size that "
              "turns a negative edge positive, so no target is shown — the "
              "number has to move first.",
        "es": "{n} calificadas, y perdiendo. Ningún tamaño de muestra convierte "
              "una ventaja negativa en positiva.",
    },
    "ev_profit_needs": {
        "en": "{n} graded. At this rate of return it would take roughly "
              "<b>{more} more</b> before the profit alone is 99% unlikely to be "
              "luck. Until then this column is a story, not evidence.",
        "es": "{n} calificadas. A este ritmo harían falta unas <b>{more} más</b> "
              "para que la ganancia por sí sola tenga 99% de no ser suerte.",
    },
    "ev_profit_proven": {
        "en": "{n} graded — enough that the return itself is now unlikely to be "
              "luck at 99% confidence. That took a long time, which is the point.",
        "es": "{n} calificadas — suficientes para que el retorno ya sea poco "
              "probable por suerte con 99% de confianza.",
    },
    "ev_clv_none": {
        "en": "No play has a recorded closing line yet. This is the column that "
              "will mean something first.",
        "es": "Ninguna jugada tiene línea de cierre registrada todavía.",
    },
    "ev_clv_early": {
        "en": "{n} plays measured against the number the market settled on. Not "
              "yet far enough from a coin flip to claim anything — but this is "
              "the figure that gets there in dozens of plays rather than "
              "thousands.",
        "es": "{n} jugadas medidas contra el número final del mercado. Todavía no "
              "lo bastante lejos de un volado para afirmar nada.",
    },
    "ev_clv_strong": {
        "en": "{n} plays measured against the number the market settled on, and "
              "the rate we beat it sits <b>{v} standard deviations</b> from "
              "chance. This is the evidence that arrives first, and the one "
              "worth judging us on.",
        "es": "{n} jugadas medidas contra el número final del mercado, y la tasa "
              "a la que le ganamos está a <b>{v} desviaciones estándar</b> del azar.",
    },
    "ev_approx": {
        "en": "Under 30 graded plays the interval above is a normal "
              "approximation applied to a distinctly non-normal thing — a single "
              "play either loses its stake or wins it times the price. Treat the "
              "range as indicative until the sample grows.",
        "es": "Con menos de 30 jugadas calificadas el intervalo de arriba es una "
              "aproximación normal aplicada a algo que no lo es.",
    },

    # ---- tables, continued
    "no_graded_short": {"en": "No graded plays yet.",
                        "es": "Aún no hay jugadas calificadas."},
    "nothing_posted":  {"en": "Nothing posted yet.", "es": "Aún no se ha publicado nada."},
    "src_value":       {"en": "Price scanner",  "es": "Escáner de precios"},
    "src_screen":      {"en": "Strikeout screens", "es": "Filtros de ponches"},

    # ---- month chart
    "chart_empty": {
        "en": "The monthly chart fills in once the first month of plays is graded.",
        "es": "El gráfico mensual se llena en cuanto se califique el primer mes de jugadas.",
    },
    "chart_alt":   {"en": "Monthly units: {v}", "es": "Unidades por mes: {v}"},
    "chart_tip":   {"en": "{month} {year} · {units} · {n} plays",
                    "es": "{month} {year} · {units} · {n} jugadas"},

    # ---- signup
    "signup_btn":   {"en": "Send me the plays", "es": "Envíame las jugadas"},
    "signup_aria":  {"en": "Email address",     "es": "Correo electrónico"},
    "signup_title": {"en": "Newsletter signup", "es": "Suscripción al boletín"},

    # ---- screen rule labels (the methodology page renders from config)
    "sl_min_pitcher_k_pct":  {"en": "Pitcher season K%",
                              "es": "K% del lanzador en la temporada"},
    "sl_min_vs_pa":          {"en": "Career PA vs this roster",
                              "es": "Turnos de por vida vs esta alineación"},
    "sl_min_vs_k_pct":       {"en": "K% vs this roster",
                              "es": "K% vs esta alineación"},
    "sl_max_vs_avg":         {"en": "Batting average vs this roster",
                              "es": "Promedio de bateo vs esta alineación"},
    "sl_max_vs_woba":        {"en": "wOBA vs this roster",
                              "es": "wOBA vs esta alineación"},
    "sl_min_opp_k_per_game": {"en": "Opponent strikeouts per game",
                              "es": "Ponches del rival por juego"},
    "sl_line_min":           {"en": "Lowest strikeout line allowed",
                              "es": "Línea de ponches más baja permitida"},
    "sl_line_max":           {"en": "Highest strikeout line allowed",
                              "es": "Línea de ponches más alta permitida"},
    "sl_worst_juice":        {"en": "Price", "es": "Precio"},
    "sl_min_k_per_9":        {"en": "Season K/9", "es": "K/9 en la temporada"},
    "sl_max_bets_per_day":   {"en": "Plays per day from this screen",
                              "es": "Jugadas por día de este filtro"},
    "sl_max_line":           {"en": "Any line at or above this",
                              "es": "Cualquier línea igual o mayor a esta"},
    "sl_banned_line":        {"en": "This exact line", "es": "Esta línea exacta"},
    "cmp_at_least": {"en": "at least",     "es": "al menos"},
    "cmp_under":    {"en": "under",        "es": "menos de"},
    "cmp_no_worse": {"en": "no worse than", "es": "no peor que"},
    "cmp_at_most":  {"en": "at most",      "es": "como máximo"},
    "cmp_never":    {"en": "never bet",    "es": "nunca se apuesta"},
    "rule_nolimit": {"en": "no limit",     "es": "sin límite"},
    "rule_off":     {"en": "off",          "es": "apagado"},
    "screen_missing": {"en": "Screen configuration not loaded.",
                       "es": "No se cargó la configuración de los filtros."},

    # ---- break-even table
    "be_edge":   {"en": "needs a real edge",      "es": "necesita ventaja real"},
    "be_even":   {"en": "a coin flip breaks even", "es": "un volado sale a mano"},
    "be_profit": {"en": "a coin flip profits",    "es": "un volado gana"},

    # ---- Brier line
    "brier_empty": {
        "en": "No rated game has finished yet. Once they start grading, this line "
              "reports how far off our probabilities were.",
        "es": "Aún no ha terminado ningún juego evaluado. Cuando empiecen a "
              "calificarse, esta línea reporta qué tan lejos estuvieron nuestras "
              "probabilidades.",
    },
    "brier_main": {
        "en": "Across {n} graded ratings our Brier score is <b style=\"color:var(--txt)\">{v}</b>. "
              "Always saying 50% scores 0.250, so lower than that is the minimum bar "
              "for being worth reading.",
        "es": "Sobre {n} evaluaciones calificadas nuestro puntaje Brier es "
              "<b style=\"color:var(--txt)\">{v}</b>. Decir siempre 50% saca 0.250, así que "
              "estar por debajo de eso es el mínimo para que valga la pena leerse.",
    },
    "brier_market": {
        "en": " The market scored <b style=\"color:var(--txt)\">{v}</b> on the same {n} games "
              "— its own vig-free number taken at the moment we rated the game, not the "
              "closing price — so we are {rel} it. Being worse is the expected outcome "
              "and we publish it either way.",
        "es": " El mercado sacó <b style=\"color:var(--txt)\">{v}</b> en esos mismos {n} juegos "
              "— su propio número sin vigorish tomado en el momento en que evaluamos el "
              "juego, no el precio de cierre — así que estamos {rel} él. Estar peor es el "
              "resultado esperado y lo publicamos de todos modos.",
    },
    "rel_better": {"en": "better than", "es": "por encima de"},
    "rel_worse":  {"en": "worse than",  "es": "por debajo de"},
    "rel_level":  {"en": "level with",  "es": "a la par de"},

    # ---- pitcher board, continued
    "no_starts":  {"en": "No starts logged yet this season.",
                   "es": "Aún no hay aperturas registradas esta temporada."},
    "pb_tip":     {"en": "{when} vs {opp} — {k} K in {ip} IP",
                   "es": "{when} vs {opp} — {k} P en {ip} EL"},
    "pb_flagtip": {"en": "Further from the posted number than the market can plausibly "
                         "be wrong — treated as our error",
                   "es": "Más lejos del número publicado de lo que el mercado puede "
                         "plausiblemente equivocarse — lo tratamos como error nuestro"},
    "pb_rank":    {"en": "{r}{ord} of {n}", "es": "{r}º de {n}"},
    "l5":         {"en": "L5", "es": "Ú5"},
    "pb_empty":   {"en": "Nothing graded yet &mdash; this fills in as rated starts finish.",
                   "es": "Aún no hay nada calificado &mdash; esto se llena conforme "
                         "terminen las aperturas evaluadas."},
    "pa_empty": {
        "en": "Nothing graded yet. Once these starts finish, this line reports how far "
              "off the projections were &mdash; and how that compares to simply reading "
              "the posted number.",
        "es": "Aún no hay nada calificado. Cuando terminen estas aperturas, esta línea "
              "reporta qué tan lejos estuvieron las proyecciones &mdash; y cómo se "
              "compara eso con simplemente leer el número publicado.",
    },
    # The noun is a separate key rather than a {s} suffix: Spanish drops the
    # accent when "proyección" becomes "proyecciones", so an appended plural
    # would spell it wrong.
    "pa_noun_one":  {"en": "graded projection",  "es": "proyección calificada"},
    "pa_noun_many": {"en": "graded projections", "es": "proyecciones calificadas"},
    "pa_main": {
        "en": "Across {n} {noun} the average miss is "
              "<b style=\"color:var(--txt)\">{mae}</b> strikeouts. Taking the posted line at "
              "face value missed by <b style=\"color:var(--txt)\">{lmae}</b>.",
        "es": "Sobre {n} {noun} el error promedio es de "
              "<b style=\"color:var(--txt)\">{mae}</b> ponches. Tomar la línea publicada tal "
              "cual falló por <b style=\"color:var(--txt)\">{lmae}</b>.",
    },
    "pa_closer": {
        "en": " We are closer than the line, which after a few hundred starts would be "
              "worth something. It is far too early to mean anything.",
        "es": " Estamos más cerca que la línea, lo que después de unos cientos de "
              "aperturas valdría algo. Es demasiado pronto para que signifique nada.",
    },
    "pa_line_closer": {
        "en": " The line is closer than we are, which is the expected result and is "
              "published either way.",
        "es": " La línea está más cerca que nosotros, que es el resultado esperado y se "
              "publica de todos modos.",
    },
    "pa_called": {
        "en": " Of the {n} starters we actually leaned on, {v}% landed on the side we "
              "called &mdash; 50% is a coin flip.",
        "es": " De los {n} abridores en los que de verdad nos inclinamos, {v}% cayó del "
              "lado que dijimos &mdash; 50% es un volado.",
    },
    "bucket_tip": {"en": "{a} of {b} landed on our side",
                   "es": "{a} de {b} cayeron de nuestro lado"},
    # ---- the "vs this opponent" line under a starter
    "gs":        {"en": "GS", "es": "AP"},   # games started / aperturas
    "vs_body":   {"en": "vs {team} &middot; {stint}{ip} {ipu} &middot; {era} {erau}",
                  "es": "vs {team} &middot; {stint}{ip} {ipu} &middot; {era} {erau}"},
    "vs_thin":   {"en": "thin", "es": "escasa"},
    "vs_tip":    {"en": "{span} — shown as context, not used in the number",
                  "es": "{span} — se muestra como contexto, no entra en el número"},
    "vs_tip_thin": {"en": "{tip}. Too few starts to mean anything.",
                    "es": "{tip}. Muy pocas aperturas para significar algo."},
    "span_career": {"en": "career", "es": "de por vida"},
    "span_season": {"en": "{v} regular season", "es": "temporada regular {v}"},
    "them":        {"en": "them", "es": "ellos"},
    "k_unit":   {"en": "K", "es": "P"},
    "k_rate":   {"en": "{v}% K", "es": "{v}% P"},
    # Projection-accuracy buckets. The scripts store an id so the label can be
    # written here instead of being frozen into the data file in one language.
    "bk_half":     {"en": "within half a strikeout", "es": "dentro de medio ponche"},
    "bk_half_one": {"en": "half to one",   "es": "de medio a uno"},
    "bk_one_two":  {"en": "one to two",    "es": "de uno a dos"},
    "bk_two_plus": {"en": "more than two", "es": "más de dos"},
    "cal_tip": {"en": "We said {a}% &middot; they won {b}%",
                "es": "Dijimos {a}% &middot; ganaron {b}%"},

    # ---- build-time page copy
    "caps_off": {
        "en": "These caps are currently switched off. Every one of them &mdash; the "
              "ceiling on high numbers, the ban on 4.5 lines, and the limit on how much "
              "juice is acceptable &mdash; has been lifted, so a play is judged on the "
              "screen conditions alone. That widens the pool considerably and removes "
              "protections that were there for a reason; the track record will show "
              "whether lifting them was right.",
        "es": "Estos topes están apagados por ahora. Todos ellos &mdash; el techo para "
              "números altos, la prohibición de las líneas de 4.5 y el límite de "
              "vigorish aceptable &mdash; fueron levantados, así que una jugada se juzga "
              "solo por las condiciones del filtro. Eso amplía bastante el universo y "
              "quita protecciones que estaban ahí por una razón; el historial dirá si "
              "levantarlas fue lo correcto.",
    },
    "caps_active": {
        "en": "Checked before any screen runs, and a play violating one is rejected no "
              "matter how good the spot looks: {v}.",
        "es": "Se revisan antes de que corra cualquier filtro, y una jugada que viole "
              "alguno se rechaza por buena que se vea la situación: {v}.",
    },
    "cap_max_line":    {"en": "nothing at or above a {v} line",
                        "es": "nada en una línea de {v} o más"},
    "cap_banned_line": {"en": "no {v} lines at all", "es": "ninguna línea de {v}"},
    "cap_worst_juice": {"en": "no price worse than {v}",
                        "es": "ningún precio peor que {v}"},
    "price_note": {
        "en": "There is no price requirement on this screen. Selecting a matchup and "
              "judging a price are separate questions, and a rule that demanded plus "
              "money was answering the second one with a coin-flip heuristic &mdash; a "
              "good spot at &minus;115 was rejected while a bad one at +105 was not. "
              "Every screen play still gets its edge measured against the vig-free "
              "consensus and its closing line recorded, which is the honest version of "
              "that check.",
        "es": "Este filtro no exige nada del precio. Escoger un enfrentamiento y juzgar "
              "un precio son preguntas distintas, y una regla que exigía dinero positivo "
              "respondía la segunda con una heurística de volado &mdash; una buena "
              "situación a &minus;115 se rechazaba y una mala a +105 no. A toda jugada de "
              "filtro se le sigue midiendo la ventaja contra el consenso sin vigorish y "
              "se le registra la línea de cierre, que es la versión honesta de esa "
              "revisión.",
    },
    "count_line_card": {
        "en": "{n} play{s} on the card. Posted at {time}, with the price and book that "
              "was available at that moment. Every one gets graded here tomorrow morning.",
        "es": "{n} jugada{s} en la cartelera. Publicada{s} a las {time}, con el precio y "
              "la casa que estaban disponibles en ese momento. Todas se califican aquí "
              "mañana por la mañana.",
    },
    "count_line_none": {
        "en": "No plays on the card today. The board was scanned and nothing cleared the "
              "edge threshold — that's a normal result, not an outage.",
        "es": "Hoy no hay jugadas en la cartelera. Se escaneó la pizarra y nada superó el "
              "umbral de ventaja — ese es un resultado normal, no una falla.",
    },
    "record_intro": {
        "en": "{n} graded plays, {p} still in flight. Nothing removed, nothing re-priced "
              "after the fact. The losing stretches are on this page too — they're the point.",
        "es": "{n} jugadas calificadas, {p} todavía en curso. Nada eliminado, nada "
              "revaluado después del hecho. Las rachas perdedoras también están en esta "
              "página — de eso se trata.",
    },
    "record_intro_empty": {
        "en": "This log starts empty, on purpose. Every play the scanner posts lands here "
              "the next morning — graded against the final score, winners and losers "
              "alike, and never edited afterward. Check back once the first cards have run.",
        "es": "Este registro empieza vacío, a propósito. Cada jugada que publica el "
              "escáner aparece aquí a la mañana siguiente — calificada contra el marcador "
              "final, ganadoras y perdedoras por igual, y nunca editada después. Vuelve "
              "cuando hayan corrido las primeras carteleras.",
    },
    "months_line": {
        "en": "{n} losing months out of {total}. Any record without red months has been edited.",
        "es": "{n} meses perdedores de {total}. Cualquier historial sin meses en rojo ha "
              "sido editado.",
    },
    "months_line_empty": {
        "en": "The monthly chart fills in as soon as the first month of plays has been graded.",
        "es": "El gráfico mensual se llena en cuanto se califique el primer mes de jugadas.",
    },
    "log_heading":       {"en": "The last {n} graded plays",
                          "es": "Las últimas {n} jugadas calificadas"},
    "log_heading_empty": {"en": "Play log", "es": "Registro de jugadas"},
    "drawdown":       {"en": "Worst peak-to-trough run so far: {v}.",
                       "es": "Peor racha de pico a valle hasta ahora: {v}."},
    "drawdown_empty": {"en": "Average so far across plays with a late line: {v}.",
                       "es": "Promedio hasta ahora en jugadas con línea tardía: {v}."},
    "eyebrow_posted": {"en": "{date} · Posted {time}",
                       "es": "{date} · Publicada a las {time}"},
    "eyebrow_scan":   {"en": "Board scanned · Next card posts at {time}",
                       "es": "Pizarra escaneada · La próxima cartelera sale a las {time}"},
    "last_graded_card": {"en": "the last graded card",
                         "es": "la última cartelera calificada"},
}


def t(key: str, lang: str = "en", **kw) -> str:
    """Look up a string. A missing key is loud rather than silent — a blank
    where a sentence should be is far harder to notice than a marker."""
    entry = T.get(key)
    if entry is None:
        return f"[[{key}]]"
    text = entry.get(lang) or entry.get("en", f"[[{key}]]")
    return text.format(**kw) if kw else text


def plural(n: int, lang: str) -> str:
    """The 's' that both languages happen to share for regular plurals.

    Callers pass this for every countable string even when the English
    template has no {s} — Spanish inflects adjectives English leaves alone
    ("1 flagged" / "1 marcado", "2 flagged" / "2 marcados"), and str.format
    ignores a keyword the template doesn't use. Supplying it unconditionally
    is what stops that asymmetry becoming a KeyError in one language only.
    """
    return "" if n == 1 else "s"


def long_date(dt, lang: str = "en") -> str:
    """'Wednesday, August 26, 2026' / 'miércoles, 26 de agosto de 2026'."""
    wd = WEEKDAYS[lang][dt.weekday()]
    mo = MONTHS[lang][dt.month - 1]
    if lang == "es":
        return f"{wd}, {dt.day} de {mo} de {dt.year}"
    return f"{wd}, {mo} {dt.day}, {dt.year}"


MONTHS_SHORT = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "es": ["ene", "feb", "mar", "abr", "may", "jun",
           "jul", "ago", "sep", "oct", "nov", "dic"],
}


def short_date(dt, lang: str = "en") -> str:
    """'Aug 26' / '26 ago'. Spanish puts the day first, as it does everywhere."""
    mo = MONTHS_SHORT[lang][dt.month - 1]
    return f"{dt.day} {mo}" if lang == "es" else f"{mo} {dt.day}"


def day_and_date(dt, lang: str = "en") -> str:
    """'Wednesday, August 26' / 'miércoles, 26 de agosto' — no year."""
    wd = WEEKDAYS[lang][dt.weekday()]
    mo = MONTHS[lang][dt.month - 1]
    if lang == "es":
        return f"{wd}, {dt.day} de {mo}"
    return f"{wd}, {mo} {dt.day}"


def reason_text(reason, lang: str = "en") -> str:
    """Render one stored reason.

    Plays written before reasons became structured data are plain strings.
    Those are passed through untouched — the archive is never rewritten, so
    an old English reason stays English rather than vanishing.
    """
    if isinstance(reason, str):
        return reason
    if not isinstance(reason, dict):
        return ""
    key = reason.get("k", "")
    template = REASONS.get(lang, REASONS["en"]).get(key)
    if not template:
        return ""
    try:
        return template.format(**{k: v for k, v in reason.items() if k != "k"})
    except (KeyError, IndexError):
        return ""
