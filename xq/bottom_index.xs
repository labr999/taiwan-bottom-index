{台股抄底指數 v1.0  — 指標腳本，請掛 TSE.TW 日線}
{===== 共用參數 =====}
input: Length(60); setinputname(1, "百分位回看天數");
{===== 量價：權重與開關 =====}
input: En_VolLow(1); setinputname(2, "啟用_量縮至低檔");
input: W_VolLow(10); setinputname(3, "權重_量縮至低檔");
input: En_Shadow(1); setinputname(4, "啟用_長下影放量");
input: W_Shadow(10); setinputname(5, "權重_長下影放量");
input: En_VolStruct(1); setinputname(6, "啟用_跌量縮漲量增");
input: W_VolStruct(10); setinputname(7, "權重_跌量縮漲量增");
input: En_Div(1); setinputname(8, "啟用_價RSI底背離");
input: W_Div(15); setinputname(9, "權重_價RSI底背離");
{===== 廣度 =====}
input: En_LimitDn(1); setinputname(10, "啟用_跌停家數高峰回落");
input: W_LimitDn(10); setinputname(11, "權重_跌停家數高峰回落");
input: En_AdvRatio(1); setinputname(12, "啟用_上漲家數比改善");
input: W_AdvRatio(10); setinputname(13, "權重_上漲家數比改善");
{===== 籌碼 =====}
input: En_Margin(1); setinputname(14, "啟用_融資餘額洗出");
input: W_Margin(10); setinputname(15, "權重_融資餘額洗出");
input: En_Maint(1); setinputname(16, "啟用_融資維持率落底回升");
input: W_Maint(10); setinputname(17, "權重_融資維持率落底回升");
input: En_SSRatio(1); setinputname(18, "啟用_券資比偏高");
input: W_SSRatio(8); setinputname(19, "權重_券資比偏高");
input: En_Foreign(1); setinputname(20, "啟用_外資賣超收斂");
input: W_Foreign(12); setinputname(21, "權重_外資賣超收斂");
input: En_Local(1); setinputname(22, "啟用_投信自營回補");
input: W_Local(8); setinputname(23, "權重_投信自營回補");
{===== 衍生品 =====}
input: En_PCR(1); setinputname(24, "啟用_選擇權買賣權未平倉比");
input: W_PCR(10); setinputname(25, "權重_選擇權買賣權未平倉比");
input: En_Basis(1); setinputname(26, "啟用_期現基差轉正");
input: W_Basis(8); setinputname(27, "權重_期現基差轉正");
input: En_FutF(1); setinputname(28, "啟用_外資期貨空單收斂");
input: W_FutF(10); setinputname(29, "權重_外資期貨空單收斂");
variable: _lb(120);
variable: _rng(0), _pct(0);
variable: _sVolLow(0), _sShadow(0), _sVolStruct(0), _sDiv(0);
variable: _sLimitDn(0), _sAdvRatio(0);
variable: _sMargin(0), _sMaint(0), _sSSRatio(0), _sForeign(0), _sLocal(0);
variable: _sPCR(0), _sBasis(0), _sFutF(0);
variable: _wSum(0), _scSum(0), _total(0);
variable: _body(0), _rangeBar(0), _lowShadow(0);
variable: _upVol(0), _dnVol(0), _volRatio(0), _adv(0), _dec(0), _advR(0);
variable: _margin(0), _maint(0), _ssr(0);
variable: _fNet(0), _fSum5(0), _locSum5(0);
variable: _pcr(0), _futC(0), _basis(0), _futNet(0);
variable: _rsiVal(0), _priceLow(False), _rsiNotLow(False);
variable: _limitDn(0);
if BarFreq <> "D" then
 RaiseRunTimeError("台股抄底指數請使用日線");
_lb = Length;
if _lb < 20 then _lb = 20;
setbackbar(Length + 30);  {百分位再取區間高低，需多留暖機 K 棒}
setfirstbardate(20190701);  {資料從 2019/07 讀起，暖機後 2020 年初即有分數}
{---------- 輔助：把數列轉成 0~100 百分位（高=接近區間高） ----------}
{ 使用方式：先把目標數列放進 value99，再算 _pct }
{===== 1 量價 =====}
{1-1 成交量落在近 N 日低檔（量縮）→ 高分}
_rng = Highest(Volume, _lb) - Lowest(Volume, _lb);
if _rng <> 0 then
 _pct = (Volume - Lowest(Volume, _lb)) / _rng * 100
else
 _pct = 50;
_sVolLow = 100 - _pct;
{1-2 長下影 + 放量：訊號型 0/100}
_rangeBar = High - Low;
_body = AbsValue(Close - Open);
if _rangeBar > 0 then
 _lowShadow = (MinList(Open, Close) - Low) / _rangeBar
else
 _lowShadow = 0;
if _lowShadow >= 0.5 and Volume > Average(Volume, 20) * 1.5 and Close >= Open then
 _sShadow = 100
else
 _sShadow = 0;
{1-3 上漲日均量 / 下跌日均量 結構（寫入數列變數再算百分位）}
_upVol = AverageIF(Close > Close[1], Volume, 10);
_dnVol = AverageIF(Close < Close[1], Volume, 10);
if _dnVol > 0 then
 _volRatio = _upVol / _dnVol
else
 _volRatio = 1;
_rng = Highest(_volRatio, _lb) - Lowest(_volRatio, _lb);
if _rng <> 0 then
 _sVolStruct = (_volRatio - Lowest(_volRatio, _lb)) / _rng * 100
else
 _sVolStruct = 50;
{1-4 價格創新低但 RSI 未創新低（底背離）}
_rsiVal = RSI(Close, 14);
_priceLow = Low <= Lowest(Low, 20);
_rsiNotLow = _rsiVal > Lowest(_rsiVal, 20) * 1.02;
if _priceLow and _rsiNotLow then
 _sDiv = 100
else
 _sDiv = 0;
{===== 2 廣度（大盤欄位，掛 TSE.TW 時取用） =====}
{2-1 跌停家數：先出現高峰（高百分位）後回落}
_limitDn = GetField("跌停家數");
_rng = Highest(_limitDn, _lb) - Lowest(_limitDn, _lb);
if _rng <> 0 then
 _pct = (_limitDn - Lowest(_limitDn, _lb)) / _rng * 100
else
 _pct = 50;
{高峰後回落：近5日高點曾偏高，且今日跌停家數下降 → 給高分；否則用「曾恐慌」的對稱分}
if Highest(_limitDn, 5) >= Highest(_limitDn, _lb) * 0.7 and _limitDn < _limitDn[1] then
 _sLimitDn = MaxList(_pct, 70)
else
 _sLimitDn = _pct * 0.5;
{2-2 上漲家數占比改善}
_adv = GetField("上漲家數");
_dec = GetField("下跌家數");
if (_adv + _dec) > 0 then
 _advR = _adv / (_adv + _dec) * 100
else
 _advR = 50;
_rng = Highest(_advR, _lb) - Lowest(_advR, _lb);
if _rng <> 0 then
 _sAdvRatio = (_advR - Lowest(_advR, _lb)) / _rng * 100
else
 _sAdvRatio = 50;
if _advR > _advR[1] then
 _sAdvRatio = MinList(_sAdvRatio + 10, 100);
{===== 3 籌碼 =====}
{3-1 融資餘額張數越低（洗出）分數越高}
_margin = GetField("融資餘額張數");
_rng = Highest(_margin, _lb) - Lowest(_margin, _lb);
if _rng <> 0 then
 _sMargin = (Highest(_margin, _lb) - _margin) / _rng * 100
else
 _sMargin = 50;
{3-2 融資維持率：低檔且回升}
_maint = GetField("融資維持率");
_rng = Highest(_maint, _lb) - Lowest(_maint, _lb);
if _rng <> 0 then
 _pct = (_maint - Lowest(_maint, _lb)) / _rng * 100
else
 _pct = 50;
_sMaint = 100 - _pct;
if _maint > _maint[1] and _maint[1] <= _maint[2] then
 _sMaint = MinList(_sMaint + 15, 100);
{3-3 券資比偏高}
_ssr = GetField("券資比");
_rng = Highest(_ssr, _lb) - Lowest(_ssr, _lb);
if _rng <> 0 then
 _sSSRatio = (_ssr - Lowest(_ssr, _lb)) / _rng * 100
else
 _sSSRatio = 50;
{3-4 外資買賣超收斂／轉買（近5日合計的百分位，越高越好）}
_fSum5 = Summation(GetField("外資買賣超"), 5);
_rng = Highest(_fSum5, _lb) - Lowest(_fSum5, _lb);
if _rng <> 0 then
 _sForeign = (_fSum5 - Lowest(_fSum5, _lb)) / _rng * 100
else
 _sForeign = 50;
{3-5 投信+自營近5日合計回補}
_locSum5 = Summation(GetField("投信買賣超"), 5) + Summation(GetField("自營商買賣超"), 5);
_rng = Highest(_locSum5, _lb) - Lowest(_locSum5, _lb);
if _rng <> 0 then
 _sLocal = (_locSum5 - Lowest(_locSum5, _lb)) / _rng * 100
else
 _sLocal = 50;
{===== 4 衍生品（跨商品，文件有範例） =====}
{4-1 台指選擇權現貨 買賣權未平倉量比率（PUT/CALL，偏高常對應避險情緒）}
if CheckSymbolField("TXO00.TF", "買賣權未平倉量比率") then begin
 _pcr = GetSymbolField("TXO00.TF", "買賣權未平倉量比率");
 _rng = Highest(_pcr, _lb) - Lowest(_pcr, _lb);
 if _rng <> 0 then
 _sPCR = (_pcr - Lowest(_pcr, _lb)) / _rng * 100
 else
 _sPCR = 50;
end else
 _sPCR = 50;
{4-2 期現基差 = 近月台指期收盤 - 現貨收盤；由負轉正／回升給分}
if CheckSymbolField("FITX*1.TF", "收盤價", "D") then begin
 _futC = GetSymbolField("FITX*1.TF", "收盤價", "D");
 _basis = _futC - Close;
 _rng = Highest(_basis, _lb) - Lowest(_basis, _lb);
 if _rng <> 0 then
 _sBasis = (_basis - Lowest(_basis, _lb)) / _rng * 100
 else
 _sBasis = 50;
 if _basis > 0 and _basis[1] <= 0 then
 _sBasis = MinList(_sBasis + 20, 100);
end else
 _sBasis = 50;
{4-3 外資期貨淨口 = 買方未平倉 - 賣方未平倉；由深空翻回（上升）給高分}
if CheckSymbolField("FITX*1.TF", "外資買方未平倉口數")
 and CheckSymbolField("FITX*1.TF", "外資賣方未平倉口數") then begin
 _futNet = GetSymbolField("FITX*1.TF", "外資買方未平倉口數")
 - GetSymbolField("FITX*1.TF", "外資賣方未平倉口數");
 _rng = Highest(_futNet, _lb) - Lowest(_futNet, _lb);
 if _rng <> 0 then
 _sFutF = (_futNet - Lowest(_futNet, _lb)) / _rng * 100
 else
 _sFutF = 50;
end else
 _sFutF = 50;
{===== 加權平均（僅加總有啟用的項目，權重自動正規化） =====}
_wSum = 0;
_scSum = 0;
if En_VolLow = 1 then begin _wSum = _wSum + W_VolLow; _scSum = _scSum + W_VolLow * _sVolLow; end;
if En_Shadow = 1 then begin _wSum = _wSum + W_Shadow; _scSum = _scSum + W_Shadow * _sShadow; end;
if En_VolStruct = 1 then begin _wSum = _wSum + W_VolStruct; _scSum = _scSum + W_VolStruct * _sVolStruct; end;
if En_Div = 1 then begin _wSum = _wSum + W_Div; _scSum = _scSum + W_Div * _sDiv; end;
if En_LimitDn = 1 then begin _wSum = _wSum + W_LimitDn; _scSum = _scSum + W_LimitDn * _sLimitDn; end;
if En_AdvRatio = 1 then begin _wSum = _wSum + W_AdvRatio; _scSum = _scSum + W_AdvRatio * _sAdvRatio; end;
if En_Margin = 1 then begin _wSum = _wSum + W_Margin; _scSum = _scSum + W_Margin * _sMargin; end;
if En_Maint = 1 then begin _wSum = _wSum + W_Maint; _scSum = _scSum + W_Maint * _sMaint; end;
if En_SSRatio = 1 then begin _wSum = _wSum + W_SSRatio; _scSum = _scSum + W_SSRatio * _sSSRatio; end;
if En_Foreign = 1 then begin _wSum = _wSum + W_Foreign; _scSum = _scSum + W_Foreign * _sForeign; end;
if En_Local = 1 then begin _wSum = _wSum + W_Local; _scSum = _scSum + W_Local * _sLocal; end;
if En_PCR = 1 then begin _wSum = _wSum + W_PCR; _scSum = _scSum + W_PCR * _sPCR; end;
if En_Basis = 1 then begin _wSum = _wSum + W_Basis; _scSum = _scSum + W_Basis * _sBasis; end;
if En_FutF = 1 then begin _wSum = _wSum + W_FutF; _scSum = _scSum + W_FutF * _sFutF; end;
if _wSum <> 0 then
 _total = _scSum / _wSum
else
 _total = 50;
plot1(_total, "抄底指數");
plot2(_total - 50, "偏離中線");
