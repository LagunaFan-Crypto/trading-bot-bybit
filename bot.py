//@version=6
strategy("Supertrend Strategy (Bot)", 
     overlay = true,
     process_orders_on_close = true,
     calc_on_every_tick = true,
     max_bars_back = 2000)

// ===================================================================
//  PARAMETRY SUPERTREND
// ===================================================================
groupST = "Supertrend"
atrPeriod = input.int(56, "Długość ATR", group=groupST)
factor    = input.float(8.12, "Współczynnik", step = 0.01, group=groupST)
[supertrend, direction] = ta.supertrend(factor, atrPeriod)
upTrend = direction < 0
downTrend = direction > 0

// ===================================================================
//  FILTR ATR
// ===================================================================
groupATR = "Filtr ATR"
atrValue = ta.atr(atrPeriod)
atrMinValue = input.float(0.35, "Minimalny ATR", step=0.0001, group=groupATR)
useAtrFilter = input.bool(true, "Włącz filtr ATR (blokada wejść przy niskim ATR)", group=groupATR)

atrOk = atrValue >= atrMinValue

// ===================================================================
//  TAKE PROFIT
// ===================================================================
groupTP = "Take Profit"
tpEnabled = input.bool(true, "Włącz TP", group=groupTP)
tpPercent = input.float(7.8, "Take Profit (%)", step=0.1, group=groupTP)
tpColorLong = input.color(color.new(color.lime, 0), "Kolor linii TP (Long)", group=groupTP)
tpColorShort = input.color(color.new(color.red, 0), "Kolor linii TP (Short)", group=groupTP)

// ===================================================================
//  WIZUALIZACJA ATR
// ===================================================================
groupATRvis = "Wizualizacja ATR"
showAtrMarkers = input.bool(true, "Pokaż status ATR (czy spełnia minimalny próg)", group=groupATRvis)
atrAboveColor = input.color(color.new(color.lime, 0), "Kolor ATR OK (powyżej minimum)", group=groupATRvis)
atrBelowColor = input.color(color.new(color.red, 0), "Kolor ATR LOW (poniżej minimum)", group=groupATRvis)
atrMarkerTransparency = input.int(0, "Przezroczystość znaczników ATR", minval=0, maxval=100, group=groupATRvis)

plotchar(showAtrMarkers and atrOk,
     title="ATR OK",
     char="·",
     location=location.top,
     color=color.new(atrAboveColor, atrMarkerTransparency),
     size=size.tiny)

plotchar(showAtrMarkers and not atrOk,
     title="ATR LOW",
     char="·",
     location=location.bottom,
     color=color.new(atrBelowColor, atrMarkerTransparency),
     size=size.tiny)

// ===================================================================
//  SYGNAŁY
// ===================================================================
longSignal  = ta.crossover(close, supertrend)
shortSignal = ta.crossunder(close, supertrend)

// ===================================================================
//  ZAMYKANIE POZYCJI — BEZ WZGLĘDU NA ATR
// ===================================================================
if strategy.position_size > 0 and shortSignal
    strategy.close("BUY", comment="Trend Change Close")
    alert('{"action":"close","symbol":"' + syminfo.ticker + '"}', alert.freq_once_per_bar_close)

if strategy.position_size < 0 and longSignal
    strategy.close("SELL", comment="Trend Change Close")
    alert('{"action":"close","symbol":"' + syminfo.ticker + '"}', alert.freq_once_per_bar_close)

// ===================================================================
//  WEJŚCIA — TYLKO GDY ATR POWYŻEJ MINIMUM
//  + WYSYŁANIE TP DO BOTA PRZY SKŁADANIU ZLECENIA
// ===================================================================
canEnter = not useAtrFilter or (useAtrFilter and atrOk)

// --- LONG ---
if canEnter and longSignal
    float tpPriceLong = na
    if tpEnabled
        tpPriceLong := close * (1 + tpPercent / 100.0)

    strategy.entry("BUY", strategy.long)

    // ⭐ POPRAWIONY ALERT — 1 LINIA, ZERO BŁĘDÓW
    string alertMsgLong = tpEnabled ? '{"action":"buy","symbol":"' + syminfo.ticker + '","tp":' + str.tostring(tpPriceLong, format.mintick) + '}' : '{"action":"buy","symbol":"' + syminfo.ticker + '"}'
    alert(alertMsgLong, alert.freq_once_per_bar_close)

// --- SHORT ---
if canEnter and shortSignal
    float tpPriceShort = na
    if tpEnabled
        tpPriceShort := close * (1 - tpPercent / 100.0)

    strategy.entry("SELL", strategy.short)

    // ⭐ POPRAWIONY ALERT — 1 LINIA, ZERO BŁĘDÓW
    string alertMsgShort = tpEnabled ? '{"action":"sell","symbol":"' + syminfo.ticker + '","tp":' + str.tostring(tpPriceShort, format.mintick) + '}' : '{"action":"sell","symbol":"' + syminfo.ticker + '"}'
    alert(alertMsgShort, alert.freq_once_per_bar_close)

// ===================================================================
//  TAKE PROFIT — WIZUALIZACJA I BACKTEST (strategy.exit ZOSTAJE)
// ===================================================================
var line tpLine = na

if tpEnabled
    if strategy.position_size > 0
        longTP = strategy.position_avg_price * (1 + tpPercent / 100)
        strategy.exit("TP Long Backtest", from_entry="BUY", limit=longTP)
        if not na(tpLine)
            line.delete(tpLine)
        tpLine := line.new(bar_index - 1, longTP, bar_index, longTP, extend = extend.right, color = tpColorLong, style = line.style_dotted, width = 1)

    if strategy.position_size < 0
        shortTP = strategy.position_avg_price * (1 - tpPercent / 100)
        strategy.exit("TP Short Backtest", from_entry="SELL", limit=shortTP)
        if not na(tpLine)
            line.delete(tpLine)
        tpLine := line.new(bar_index - 1, shortTP, bar_index, shortTP, extend = extend.right, color = tpColorShort, style = line.style_dotted, width = 1)

    if strategy.position_size == 0 and not na(tpLine)
        line.delete(tpLine)
        tpLine := na

// ===================================================================
//  KOLOROWANIE ŚWIEC WG POZYCJI
// ===================================================================
groupCOL = "Kolory świec"
longColor    = input.color(color.new(color.lime, 0), "Kolor świec (Long)", group=groupCOL)
shortColor   = input.color(color.new(color.red, 0), "Kolor świec (Short)", group=groupCOL)
neutralColor = input.color(color.new(color.gray, 70), "Kolor świec (Neutralne)", group=groupCOL)

inLong  = strategy.position_size > 0
inShort = strategy.position_size < 0

barcolor(
     inLong  ? longColor :
     inShort ? shortColor :
     neutralColor)

// ===================================================================
//  LINIA SUPERTREND
// ===================================================================
plot(supertrend, color=upTrend ? color.new(color.lime, 0) : color.new(color.red, 0), linewidth=2, title="Supertrend")

// === BOX 1% PROWIZJI ===
var box provBox = na
provPerc = 1.0

if longSignal
    entryPrice = close
    provBox := box.new(left=bar_index, right=bar_index+1, top=entryPrice*(1+provPerc/100), bottom=entryPrice, bgcolor=color.new(color.lime, 80), border_color=na)
if shortSignal
    entryPrice = close
    provBox := box.new(left=bar_index, right=bar_index+1, top=entryPrice, bottom=entryPrice*(1-provPerc/100), bgcolor=color.new(color.red, 80), border_color=na)
if not na(provBox)
    box.set_right(provBox, bar_index + 1)

// === TRWAŁA LINIA TP ===
var line[]  tpLines  = array.new_line()
var label[] tpLabels = array.new_label()

tpLineWidth = 1
tpLineStyleFinal = line.style_dotted

newLong   = strategy.position_size > 0 and strategy.position_size[1] <= 0
newShort  = strategy.position_size < 0 and strategy.position_size[1] >= 0
closedPos = strategy.position_size == 0 and strategy.position_size[1] != 0

if tpEnabled
    if newLong
        tpPrice = strategy.position_avg_price * (1 + tpPercent / 100)
        tpLineColor = tpColorLong
        l   = line.new(bar_index, tpPrice, bar_index, tpPrice, color=tpLineColor, width=tpLineWidth, style=tpLineStyleFinal)
        lbl = label.new(bar_index, tpPrice, "🎯 TP " + str.tostring(tpPercent, "0.0") + "%", style=label.style_label_left, textcolor=tpLineColor, color=color.new(color.black, 80))
        array.push(tpLines, l), array.push(tpLabels, lbl)

    if newShort
        tpPrice = strategy.position_avg_price * (1 - tpPercent / 100)
        tpLineColor = tpColorShort
        l   = line.new(bar_index, tpPrice, bar_index, tpPrice, color=tpLineColor, width=tpLineWidth, style=tpLineStyleFinal)
        lbl = label.new(bar_index, tpPrice, "🎯 TP " + str.tostring(tpPercent, "0.0") + "%", style=label.style_label_left, textcolor=tpLineColor, color=color.new(color.black, 80))
        array.push(tpLines, l), array.push(tpLabels, lbl)

    if strategy.position_size != 0 and array.size(tpLines) > 0
        lastLine  = array.get(tpLines,  array.size(tpLines)  - 1)
        lastLabel = array.get(tpLabels, array.size(tpLabels) - 1)
        line.set_xy2(lastLine, bar_index, line.get_y1(lastLine))
        label.set_x(lastLabel, bar_index + 1)
        label.set_y(lastLabel, line.get_y1(lastLine))
        label.set_text(lastLabel, "🎯 TP " + str.tostring(tpPercent, "0.0") + "%")

    if closedPos and array.size(tpLines) > 0
        lastLine  = array.get(tpLines,  array.size(tpLines)  - 1)
        lastLabel = array.get(tpLabels, array.size(tpLabels) - 1)
        yPos = line.get_y1(lastLine)
        line.set_xy2(lastLine, bar_index, yPos)
        label.set_x(lastLabel, bar_index)
        label.set_y(lastLabel, yPos)

// === WSKAŹNIK ZYSKU/STRATY ===
groupProfit = "Wskaźnik zysku/straty"
showProfitTable = input.bool(true, "Pokaż bieżący zysk/stratę (prawy górny róg)", group=groupProfit)
var table profitTable = na
if showProfitTable and na(profitTable)
    profitTable := table.new(position.top_right, 1, 1, border_width=1, border_color=color.new(color.gray, 80))

if showProfitTable and barstate.isrealtime
    if strategy.position_size != 0
        entryPriceRT   = strategy.position_avg_price
        profitPercentT = strategy.position_size > 0 ? ((close - entryPriceRT) / entryPriceRT) * 100 : ((entryPriceRT - close) / entryPriceRT) * 100
        profitColor    = profitPercentT >= 0 ? color.new(color.lime, 0) : color.new(color.red, 0)
        table.cell(profitTable, 0, 0, "💰 Zysk: " + str.tostring(profitPercentT, "0.00") + "%", text_color=profitColor, text_size=size.large, bgcolor=color.new(color.black, 75))
    else
        table.cell(profitTable, 0, 0, "⚫ Brak pozycji", text_color=color.new(color.gray, 70), text_size=size.large, bgcolor=color.new(color.black, 85))
